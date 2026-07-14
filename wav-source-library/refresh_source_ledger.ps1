$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$exact = @{
    '04_ice_ocean/noaa_iceberg_calving_3x.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/sounds/A53JD33Calving_3x.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '04_ice_ocean/noaa_iceberg_harmonic_tremor_3x.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/sounds/HarmonicTremor2006_215_09_20UsedOnBloopWebsite.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '04_ice_ocean/noaa_icequake_bloop_16x.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/sounds/bloop.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '04_ice_ocean/noaa_iceberg_grounding_slowdown_16x.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/sounds/noise97139.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '04_ice_ocean/noaa_humpback_with_ship.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/multimedia/HB-ship-SBNMS.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '04_ice_ocean/noaa_humpback_with_snapping_shrimp.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/multimedia/HB-ship-AMSNP.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '04_ice_ocean/noaa_challenger_deep_ship_traffic_10x.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/multimedia/ChallengerDeep_25June2020-011003_ShipGlorius_modem_x10%20%282%29.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '04_ice_ocean/noaa_damselfish_hydrophone.wav' = @('NOAA PMEL Acoustics Program','https://www.pmel.noaa.gov/acoustics/multimedia/Damselfish%20Clip_American%20Samoa%20Hydrophone.wav','original WAV unchanged','Public information; cite NOAA PMEL Acoustics Program and source URL','NOAA PMEL Acoustics Program')
    '05_seismic_planetary/nasa_insight_first_likely_marsquake_sol128.wav' = @('NASA/JPL-Caltech/CNES/IPGP/Imperial College London','https://assets.science.nasa.gov/content/dam/science/psd/mars/downloadable_items/4/42692_insight_quake_sol128.wav','original WAV unchanged; publisher sped sensor data 60x','NASA media usage guidelines; no endorsement','NASA/JPL-Caltech/CNES/IPGP/Imperial College London')
    '05_seismic_planetary/nasa_insight_martian_impact_100x.wav' = @('NASA/JPL-Caltech/CNES/Imperial College London','https://assets.science.nasa.gov/content/dam/science/psd/mars/downloadable_items/4/7/47702_PIA25582-Audio_NASAs_InSight_Records_the_Sound_of_a_Martian_Impact-FIGURE_A-PJ_ONLY.wav','original WAV unchanged; publisher sped sensor data 100x','NASA media usage guidelines; no endorsement','NASA/JPL-Caltech/CNES/Imperial College London')
    '05_seismic_planetary/nasa_perseverance_first_audio_raw.wav' = @('NASA/JPL-Caltech/LANL/CNES/CNRS/ISAE-Supaero','https://assets.science.nasa.gov/content/dam/science/psd/mars/downloadable_items/4/5/45824_SCAM_MIC_SOL001_RUN001.wav','original WAV unchanged','NASA media usage guidelines; no endorsement','NASA/JPL-Caltech/LANL/CNES/CNRS/ISAE-Supaero')
    '05_seismic_planetary/nasa_perseverance_includes_rover_noise.wav' = @('NASA/JPL-Caltech','https://assets.science.nasa.gov/content/dam/science/psd/mars/downloadable_items/4/5/45705_1st_Sounds_from_Mars_includes_rover_self-noise.wav','original WAV unchanged','NASA media usage guidelines; no endorsement','NASA/JPL-Caltech')
    '05_seismic_planetary/nasa_perseverance_filtered_rover_noise.wav' = @('NASA/JPL-Caltech','https://assets.science.nasa.gov/content/dam/science/psd/mars/downloadable_items/4/5/45704_1st_Sounds_from_Mars_filters_out_rover_self-noise.wav','original WAV unchanged; publisher-filtered version','NASA media usage guidelines; no endorsement','NASA/JPL-Caltech')
    '03_space_plasma/uiowa_cluster_earth_chorus.wav' = @('University of Iowa Radio and Plasma Wave Group','https://space.physics.uiowa.edu/~dag/chorus.wav','original WAV unchanged; scientific sonification','UNKNOWN - no explicit reuse license found; verify before public release','University of Iowa Radio and Plasma Wave Group')
    '03_space_plasma/uiowa_dynamics_explorer_saucers.wav' = @('University of Iowa Radio and Plasma Wave Group','https://space.physics.uiowa.edu/~dag/8402916.wav','original WAV unchanged; scientific sonification','UNKNOWN - no explicit reuse license found; verify before public release','University of Iowa Radio and Plasma Wave Group')
    '03_space_plasma/uiowa_cluster_single_whistler.wav' = @('University of Iowa Radio and Plasma Wave Group','https://www-pw.physics.uiowa.edu/plasma-wave/istp/cluster/sounds/whistler.wav','original WAV unchanged; scientific sonification','UNKNOWN - no explicit reuse license found; verify before public release','University of Iowa Radio and Plasma Wave Group')
    '07_pulsars/jodrell_47tuc1_8000.wav' = @('Jodrell Bank Centre for Astrophysics','https://www.jb.man.ac.uk/research/pulsar/Education/Sounds/47tuc1-8000.wav','original WAV unchanged; radio data rendered as audio','UNKNOWN - no explicit reuse license found; verify before public release','Jodrell Bank Centre for Astrophysics, University of Manchester')
    '07_pulsars/jodrell_47tuc2_8000.wav' = @('Jodrell Bank Centre for Astrophysics','https://www.jb.man.ac.uk/research/pulsar/Education/Sounds/47tuc2-8000.wav','original WAV unchanged; radio data rendered as audio','UNKNOWN - no explicit reuse license found; verify before public release','Jodrell Bank Centre for Astrophysics, University of Manchester')
}

$rows = foreach ($file in Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.wav' | Sort-Object FullName) {
    $rel = $file.FullName.Substring($root.Length + 1).Replace('\','/')
    if ($exact.ContainsKey($rel)) {
        $meta = $exact[$rel]
    } elseif ($rel.StartsWith('08_clean_instruments/')) {
        $meta = @('University of Iowa Electronic Music Studios','https://theremin.music.uiowa.edu/MIS.html','official AIFF decoded to PCM s16le WAV; no normalization','May be downloaded and used for any projects without restrictions','Lawrence Fritts, University of Iowa Electronic Music Studios')
    } elseif ($rel.StartsWith('09_orchestral_philharmonia/')) {
        $meta = @('Philharmonia Orchestra','https://philharmonia.co.uk/resources/sound-samples/','official MP3 decoded to PCM s16le WAV; no normalization','Commercial use allowed; do not sell or redistribute unchanged as samples or a sampler instrument','Philharmonia Orchestra')
    } else {
        $meta = @('LOCAL / UNKNOWN','','no declared transformation','UNKNOWN - classify before public release','')
    }

    $probe = ffprobe.exe -v error -select_streams a:0 -show_entries stream=sample_rate,channels,bits_per_sample,codec_name -show_entries format=duration -of json $file.FullName | ConvertFrom-Json
    if (-not $probe.streams -or -not $probe.format) { throw "ffprobe failed: $rel" }
    [pscustomobject]@{
        path = $rel
        source_org = $meta[0]
        source_url = $meta[1]
        transformation = $meta[2]
        usage_terms = $meta[3]
        credit = $meta[4]
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
        bytes = $file.Length
        codec = $probe.streams[0].codec_name
        sample_rate_hz = [int]$probe.streams[0].sample_rate
        channels = [int]$probe.streams[0].channels
        bits_per_sample = [int]$probe.streams[0].bits_per_sample
        duration_seconds = [math]::Round([double]$probe.format.duration, 6)
    }
}

$rows | Export-Csv -LiteralPath (Join-Path $root 'SOURCE_LEDGER.csv') -NoTypeInformation -Encoding utf8
Write-Host "Wrote SOURCE_LEDGER.csv with $($rows.Count) WAV rows."
