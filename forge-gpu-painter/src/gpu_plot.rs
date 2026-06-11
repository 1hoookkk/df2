//! GPU plot layer — hero curve core + glow + underfill, frame ghosts and the
//! brush footprint, rendered by one WGSL fragment shader through egui_wgpu's
//! paint callback (the viewport is pre-set to the callback rect, so the
//! fullscreen triangle maps exactly onto the plot).
//!
//! The shader mirrors the CPU mappings bit-for-bit: log-spaced dB rows
//! (`freq_at`), display axis log or Bark (`axis_t`/`axis_f`, Traunmüller
//! constants 26.81 forward / 26.28 inverse — same asymmetry as main.rs), and
//! the `y_for_db` clamp. Data is the same packed-runtime dB rows the egui
//! fallback draws; this layer changes pixels, never truth.

use eframe::egui_wgpu::{self, wgpu};

pub const ROWS: u32 = 4; // 0 = response · 1 = ghost low · 2 = ghost high · 3 = Q-compare

#[repr(C)]
#[derive(Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
pub struct PlotUniforms {
    pub rect_px: [f32; 2],
    pub db_min_max: [f32; 2],
    /// x01 (axis position of the hand), halfwidth01 (brush half-width on the
    /// axis), strength (0 = idle, 1 = moulding), unused
    pub hand: [f32; 4],
    /// ghosts on, n_bins, bark axis, pixels_per_point
    pub flags: [f32; 4],
}

pub struct PlotGpu {
    pipeline: wgpu::RenderPipeline,
    bind_group: wgpu::BindGroup,
    uniforms: wgpu::Buffer,
    tex: wgpu::Texture,
    n_bins: u32,
}

pub struct PlotCallback {
    pub rows: Vec<f32>, // ROWS * n_bins, row-major
    pub uni: PlotUniforms,
}

impl egui_wgpu::CallbackTrait for PlotCallback {
    fn prepare(
        &self,
        _device: &wgpu::Device,
        queue: &wgpu::Queue,
        _screen: &egui_wgpu::ScreenDescriptor,
        _encoder: &mut wgpu::CommandEncoder,
        resources: &mut egui_wgpu::CallbackResources,
    ) -> Vec<wgpu::CommandBuffer> {
        let Some(r) = resources.get::<PlotGpu>() else {
            return Vec::new();
        };
        queue.write_buffer(&r.uniforms, 0, bytemuck::bytes_of(&self.uni));
        if self.rows.len() as u32 == ROWS * r.n_bins {
            queue.write_texture(
                wgpu::ImageCopyTexture {
                    texture: &r.tex,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                bytemuck::cast_slice(&self.rows),
                wgpu::ImageDataLayout {
                    offset: 0,
                    bytes_per_row: Some(4 * r.n_bins),
                    rows_per_image: Some(ROWS),
                },
                wgpu::Extent3d {
                    width: r.n_bins,
                    height: ROWS,
                    depth_or_array_layers: 1,
                },
            );
        }
        Vec::new()
    }

    fn paint(
        &self,
        _info: eframe::egui::PaintCallbackInfo,
        render_pass: &mut wgpu::RenderPass<'static>,
        resources: &egui_wgpu::CallbackResources,
    ) {
        let Some(r) = resources.get::<PlotGpu>() else {
            return;
        };
        render_pass.set_pipeline(&r.pipeline);
        render_pass.set_bind_group(0, &r.bind_group, &[]);
        render_pass.draw(0..3, 0..1);
    }
}

/// Build the pipeline + resources and park them in the renderer's resource
/// map. Returns false (egui fallback stays active) if there is no wgpu state.
pub fn register(rs: &egui_wgpu::RenderState, n_bins: u32) -> bool {
    let device = &rs.device;

    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("plot_shader"),
        source: wgpu::ShaderSource::Wgsl(SHADER.into()),
    });

    let uniforms = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("plot_uniforms"),
        size: std::mem::size_of::<PlotUniforms>() as u64,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });

    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("plot_rows"),
        size: wgpu::Extent3d {
            width: n_bins,
            height: ROWS,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::R32Float,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    let tex_view = tex.create_view(&wgpu::TextureViewDescriptor::default());

    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("plot_bgl"),
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: false },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
        ],
    });

    let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("plot_bg"),
        layout: &bgl,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: uniforms.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::TextureView(&tex_view),
            },
        ],
    });

    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("plot_layout"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });

    // premultiplied-over: the shader emits light (col) + occlusion (alpha)
    let blend = wgpu::BlendState {
        color: wgpu::BlendComponent {
            src_factor: wgpu::BlendFactor::One,
            dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha,
            operation: wgpu::BlendOperation::Add,
        },
        alpha: wgpu::BlendComponent::OVER,
    };

    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("plot_pipeline"),
        layout: Some(&layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: "vs_main",
            compilation_options: Default::default(),
            buffers: &[],
        },
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: "fs_main",
            compilation_options: Default::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format: rs.target_format,
                blend: Some(blend),
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        multiview: None,
        cache: None,
    });

    rs.renderer.write().callback_resources.insert(PlotGpu {
        pipeline,
        bind_group,
        uniforms,
        tex,
        n_bins,
    });
    true
}

const SHADER: &str = r#"
const F_MIN: f32 = 30.0;
const F_MAX: f32 = 16000.0;

// palette (gamma space, == painter::theme Color32 consts)
const TRUTH: vec3<f32>    = vec3<f32>(0.949, 0.937, 0.910);
const ICE: vec3<f32>      = vec3<f32>(0.184, 0.784, 0.800);
const GHOST_LO: vec3<f32> = vec3<f32>(0.902, 0.631, 0.231);
const GHOST_HI: vec3<f32> = vec3<f32>(0.337, 0.929, 0.439);

struct U {
    rect_px: vec2<f32>,
    db: vec2<f32>,
    hand: vec4<f32>,
    flags: vec4<f32>,
}
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var rows_tex: texture_2d<f32>;

struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VOut {
    let x = f32(i32(vi & 1u)) * 4.0 - 1.0;
    let y = f32(i32(vi >> 1u)) * 4.0 - 1.0;
    var out: VOut;
    out.pos = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>(x * 0.5 + 0.5, 0.5 - y * 0.5); // uv.y = 0 at top
    return out;
}

// display axis position 0..1 -> frequency (mirrors axis_f, incl. the
// 26.81 / 26.28 Traunmüller asymmetry of the CPU code)
fn axis_freq(t: f32) -> f32 {
    let tc = clamp(t, 0.0, 1.0);
    if (u.flags.z > 0.5) {
        let z0 = 26.81 * F_MIN / (1960.0 + F_MIN) - 0.53;
        let z1 = 26.81 * F_MAX / (1960.0 + F_MAX) - 0.53;
        let z = z0 + tc * (z1 - z0);
        return clamp(1960.0 * (z + 0.53) / (26.28 - z), F_MIN, F_MAX);
    }
    return F_MIN * pow(F_MAX / F_MIN, tc);
}

// dB of a row at a pixel x — rows are log-spaced bins regardless of axis
fn db_row(row: i32, x_px: f32) -> f32 {
    let n = u.flags.y;
    let f = axis_freq(x_px / u.rect_px.x);
    let xb = clamp(log2(f / F_MIN) / log2(F_MAX / F_MIN), 0.0, 1.0) * (n - 1.0);
    let i0 = i32(floor(xb));
    let i1 = min(i0 + 1, i32(n) - 1);
    let fr = xb - f32(i0);
    let a = textureLoad(rows_tex, vec2<i32>(i0, row), 0).r;
    let b = textureLoad(rows_tex, vec2<i32>(i1, row), 0).r;
    return mix(a, b, fr);
}

fn y_row(row: i32, x_px: f32) -> f32 {
    let db = clamp(db_row(row, x_px), u.db.x, u.db.y);
    let t = (db - u.db.x) / (u.db.y - u.db.x);
    return (1.0 - t) * u.rect_px.y;
}

// slope-corrected distance so steep slopes keep line weight
fn dist_row(row: i32, p: vec2<f32>) -> f32 {
    let yc = y_row(row, p.x);
    let y1 = y_row(row, p.x + 1.5);
    let y0 = y_row(row, p.x - 1.5);
    let slope = (y1 - y0) / 3.0;
    return abs(p.y - yc) / sqrt(1.0 + slope * slope);
}

fn rounded_mask(p: vec2<f32>) -> f32 {
    // match the plot panel's 6 px corner rounding
    let half = u.rect_px * 0.5;
    let d = abs(p - half) - half + vec2<f32>(6.0, 6.0);
    let sd = length(max(d, vec2<f32>(0.0, 0.0))) + min(max(d.x, d.y), 0.0) - 6.0;
    return smoothstep(0.5, -0.5, sd);
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
    let ppp = max(u.flags.w, 0.5);
    let p = in.uv * u.rect_px;
    var col = vec3<f32>(0.0);
    var alpha = 0.0;

    let yc = y_row(0, p.x);

    // underfill: light pooling below the hero curve, fading down
    if (p.y > yc) {
        let f = exp(-(p.y - yc) / (u.rect_px.y * 0.20));
        col += ICE * 0.062 * f;
        alpha = max(alpha, 0.13 * f);
    }

    // frame ghosts: thin, no glow
    if (u.flags.x > 0.5) {
        let dl = dist_row(1, p);
        let ll = smoothstep(1.4 * ppp, 0.4 * ppp, dl);
        col += GHOST_LO * ll * 0.22;
        alpha = max(alpha, ll * 0.22);
        let dh = dist_row(2, p);
        let lh = smoothstep(1.4 * ppp, 0.4 * ppp, dh);
        col += GHOST_HI * lh * 0.22;
        alpha = max(alpha, lh * 0.22);
    }

    // Q-compare overlay (hold C): the opposite-Q cascade, desk-sheet red
    if (u.hand.w > 0.5) {
        let dq = dist_row(3, p);
        let lq = smoothstep(1.5 * ppp, 0.5 * ppp, dq);
        col += vec3<f32>(0.898, 0.282, 0.235) * lq * 0.5;
        alpha = max(alpha, lq * 0.5);
    }

    // brush footprint while moulding: soft column + contact glow on the curve
    if (u.hand.z > 0.5) {
        let hx = u.hand.x * u.rect_px.x;
        let sx = max(u.hand.y * u.rect_px.x, 2.0);
        let band = exp(-0.5 * pow((p.x - hx) / sx, 2.0));
        col += ICE * band * 0.030;
        alpha = max(alpha, band * 0.06);
        let dc = distance(p, vec2<f32>(hx, y_row(0, hx)));
        let cg = exp(-dc / (16.0 * ppp));
        col += ICE * cg * 0.22;
        alpha = max(alpha, cg * 0.25);
    }

    // the hero: ice glow falloff + white core
    let d0 = dist_row(0, p);
    let glow = exp(-d0 / (7.0 * ppp));
    col += ICE * glow * 0.16;
    alpha = max(alpha, glow * 0.20);
    let core = smoothstep(1.8 * ppp, 0.7 * ppp, d0);
    col = mix(col, TRUTH, core);
    alpha = max(alpha, core * 0.98);

    let m = rounded_mask(p);
    return vec4<f32>(col * m, alpha * m);
}
"#;
