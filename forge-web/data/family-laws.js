export const FAMILY_AUTHORING = {
  "format": "forge-web-family-laws-v2",
  "source": {
    "laws": "tools/build_forge_family_data.py:FUNDAMENTAL_SEEDS",
    "fundamentals": "dev/tmp/measured_foundations/summary.json",
    "vocabulary": "dev/tmp/measured_foundations/{foundation_families.csv,authoring_rails.csv,report.md}",
    "boundary": "clean-room constructors only; no protected bytes, packed words, endpoint curves, names, or preset tables are copied"
  },
  "rails": [
    {
      "kind": "pole",
      "hz": 390.0,
      "band": "low-mid",
      "hits": 370,
      "states": "GRID:355;CENTER:6;PUSH_HOME:3;AWAY:2;HOME:2"
    },
    {
      "kind": "pole",
      "hz": 194.0,
      "band": "low",
      "hits": 292,
      "states": "GRID:279;CENTER:4;PUSH_HOME:3;AWAY:2;HOME:2"
    },
    {
      "kind": "zero",
      "hz": 9650.0,
      "band": "air",
      "hits": 268,
      "states": "GRID:213;HOME:13;CENTER:12;AWAY:10;PUSH_HOME:10"
    },
    {
      "kind": "zero",
      "hz": 4440.0,
      "band": "tear",
      "hits": 262,
      "states": "GRID:212;HOME:10;AWAY:10;CENTER:10;PUSH_HOME:10"
    },
    {
      "kind": "zero",
      "hz": 2220.0,
      "band": "bite",
      "hits": 262,
      "states": "GRID:212;HOME:10;AWAY:10;CENTER:10;PUSH_HOME:10"
    },
    {
      "kind": "zero",
      "hz": 8875.0,
      "band": "air",
      "hits": 260,
      "states": "GRID:209;AWAY:11;HOME:10;CENTER:10;PUSH_HOME:10"
    },
    {
      "kind": "pole",
      "hz": 780.0,
      "band": "mouth",
      "hits": 203,
      "states": "PUSH_AWAY:173;GRID:24;AWAY:2;HOME:2;PUSH_HOME:2"
    },
    {
      "kind": "zero",
      "hz": 780.0,
      "band": "mouth",
      "hits": 198,
      "states": "AWAY:174;GRID:21;CENTER:2;PUSH_AWAY:1"
    },
    {
      "kind": "zero",
      "hz": 785.0,
      "band": "mouth",
      "hits": 157,
      "states": "AWAY:121;GRID:24;PUSH_HOME:4;PUSH_AWAY:4;HOME:4"
    },
    {
      "kind": "pole",
      "hz": 785.0,
      "band": "mouth",
      "hits": 143,
      "states": "PUSH_AWAY:129;GRID:14"
    }
  ],
  "families": [
    {
      "id": "root_contrary_bp_shelf",
      "family": "root_crossing",
      "title": "CONTRARY BP SHELF",
      "intent": "A band-pass window whose shelf frame and zeros travel against the pole rows.",
      "bias": "Use when the center should feel like a moving window, not a polite EQ bump.",
      "move": "contrary crossing / band-pass shelf",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 194.0,
        "tiltDb": 8.0,
        "canyonDepth": 27.0,
        "qCrank": 0.78,
        "morphSpread": 0.86,
        "density": 0.78
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_contrary_bp_shelf",
        "family": "root_crossing",
        "title": "CONTRARY BP SHELF",
        "intent": "A band-pass window whose shelf frame and zeros travel against the pole rows.",
        "bias": "Use when the center should feel like a moving window, not a polite EQ bump.",
        "move": "contrary crossing / band-pass shelf",
        "anchor_hz": 194.0,
        "anchor_gain_db": 4.5,
        "tilt_db": 8.0,
        "canyon_depth": 27.0,
        "q_crank": 0.78,
        "morph_spread": 0.86,
        "density": 0.78,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 194.0,
            "gain_db": 3.5,
            "bw_oct": 2.6,
            "zero_offset_oct": -1.25,
            "morph_oct": 0.22,
            "zero_morph_oct": 1.35,
            "zero_secondary_oct": -0.35,
            "q_weight": 0.65
          },
          {
            "role": "bp_lower_wall",
            "fc_hz": 545.0,
            "gain_db": -6.5,
            "bw_oct": 0.85,
            "zero_offset_oct": -1.15,
            "morph_oct": 1.05,
            "zero_morph_oct": -1.05,
            "zero_secondary_oct": 0.25,
            "q_weight": 0.9
          },
          {
            "role": "bp_mouth_peak",
            "fc_hz": 780.0,
            "gain_db": 5.2,
            "bw_oct": 0.72,
            "zero_offset_oct": 0.62,
            "morph_oct": 1.25,
            "zero_morph_oct": -1.1,
            "zero_secondary_oct": 0.15,
            "q_weight": 1.0
          },
          {
            "role": "shelf_hinge",
            "fc_hz": 2220.0,
            "gain_db": 2.8,
            "bw_oct": 1.25,
            "zero_offset_oct": -0.78,
            "morph_oct": -0.65,
            "zero_morph_oct": 1.18,
            "zero_secondary_oct": -0.22,
            "q_weight": 0.82
          },
          {
            "role": "remote_canyon",
            "fc_hz": 4440.0,
            "gain_db": -9.0,
            "bw_oct": 0.58,
            "zero_offset_oct": -1.85,
            "morph_oct": -0.55,
            "zero_morph_oct": 1.75,
            "zero_secondary_oct": 0.42,
            "q_weight": 0.95
          },
          {
            "role": "air_kill",
            "fc_hz": 9650.0,
            "gain_db": -5.8,
            "bw_oct": 1.1,
            "zero_offset_oct": 0.72,
            "morph_oct": -1.0,
            "zero_morph_oct": -1.05,
            "zero_secondary_oct": 0.35,
            "q_weight": 0.55
          }
        ]
      },
      "roles": [
        "anchor",
        "bp_lower_wall",
        "bp_mouth_peak",
        "shelf_hinge",
        "remote_canyon",
        "air_kill"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 194.0,
            "poleR": 0.9684281,
            "zeroHz": 81.567,
            "zeroR": 0.545,
            "gain": 0.025
          },
          {
            "role": "bp_lower_wall",
            "poleHz": 545.0,
            "poleR": 0.5025,
            "zeroHz": 245.5908,
            "zeroR": 0.92,
            "gain": 3.75
          },
          {
            "role": "bp_mouth_peak",
            "poleHz": 780.0,
            "poleR": 0.9688621,
            "zeroHz": 1198.7626,
            "zeroR": 0.545,
            "gain": 0.0712963
          },
          {
            "role": "shelf_hinge",
            "poleHz": 2220.0,
            "poleR": 0.8525017,
            "zeroHz": 1292.8543,
            "zeroR": 0.545,
            "gain": 0.5609694
          },
          {
            "role": "remote_canyon",
            "poleHz": 4440.0,
            "poleR": 0.5025,
            "zeroHz": 1231.6221,
            "zeroR": 0.92,
            "gain": 3.75
          },
          {
            "role": "air_kill",
            "poleHz": 9650.0,
            "poleR": 0.5025,
            "zeroHz": 15895.3066,
            "zeroR": 0.92,
            "gain": 0.3649703
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 221.1855,
            "poleR": 0.9684281,
            "zeroHz": 182.3938,
            "zeroR": 0.545,
            "gain": 0.025
          },
          {
            "role": "bp_lower_wall",
            "poleHz": 1019.123,
            "poleR": 0.5025,
            "zeroHz": 131.3354,
            "zeroR": 0.92,
            "gain": 3.75
          },
          {
            "role": "bp_mouth_peak",
            "poleHz": 1643.2432,
            "poleR": 0.9688621,
            "zeroHz": 622.2413,
            "zeroR": 0.545,
            "gain": 0.32127
          },
          {
            "role": "shelf_hinge",
            "poleHz": 1506.8749,
            "poleR": 0.8525017,
            "zeroHz": 2612.3708,
            "zeroR": 0.545,
            "gain": 0.2371867
          },
          {
            "role": "remote_canyon",
            "poleHz": 3198.864,
            "poleR": 0.5025,
            "zeroHz": 3495.6474,
            "zeroR": 0.92,
            "gain": 1.3036349
          },
          {
            "role": "air_kill",
            "poleHz": 5316.6922,
            "poleR": 0.5025,
            "zeroHz": 8500.3895,
            "zeroR": 0.92,
            "gain": 0.4022667
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 194.0,
            "poleR": 0.9999,
            "zeroHz": 63.9961,
            "zeroR": 0.57542,
            "gain": 0.025
          },
          {
            "role": "bp_lower_wall",
            "poleHz": 545.0,
            "poleR": 0.5727,
            "zeroHz": 292.0583,
            "zeroR": 0.93404,
            "gain": 3.75
          },
          {
            "role": "bp_mouth_peak",
            "poleHz": 780.0,
            "poleR": 0.9930717,
            "zeroHz": 1330.1104,
            "zeroR": 0.5918,
            "gain": 0.0808796
          },
          {
            "role": "shelf_hinge",
            "poleHz": 2220.0,
            "poleR": 0.9467776,
            "zeroHz": 1110.0,
            "zeroR": 0.583376,
            "gain": 0.636464
          },
          {
            "role": "remote_canyon",
            "poleHz": 4440.0,
            "poleR": 0.5766,
            "zeroHz": 1647.8212,
            "zeroR": 0.93482,
            "gain": 3.75
          },
          {
            "role": "air_kill",
            "poleHz": 9650.0,
            "poleR": 0.5454,
            "zeroHz": 18750.0,
            "zeroR": 0.92858,
            "gain": 0.3447375
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 221.1855,
            "poleR": 0.9999,
            "zeroHz": 143.1033,
            "zeroR": 0.57542,
            "gain": 0.025
          },
          {
            "role": "bp_lower_wall",
            "poleHz": 1019.123,
            "poleR": 0.5727,
            "zeroHz": 156.185,
            "zeroR": 0.93404,
            "gain": 3.75
          },
          {
            "role": "bp_mouth_peak",
            "poleHz": 1643.2432,
            "poleR": 0.9930717,
            "zeroHz": 690.4199,
            "zeroR": 0.5918,
            "gain": 0.3968723
          },
          {
            "role": "shelf_hinge",
            "poleHz": 1506.8749,
            "poleR": 0.9467776,
            "zeroHz": 2242.8913,
            "zeroR": 0.583376,
            "gain": 0.2339606
          },
          {
            "role": "remote_canyon",
            "poleHz": 3198.864,
            "poleR": 0.5766,
            "zeroHz": 4676.923,
            "zeroR": 0.93482,
            "gain": 0.6457937
          },
          {
            "role": "air_kill",
            "poleHz": 5316.6922,
            "poleR": 0.5454,
            "zeroHz": 10834.2617,
            "zeroR": 0.92858,
            "gain": 0.2668965
          }
        ]
      }
    },
    {
      "id": "root_peak_shelf_morph",
      "family": "root_shelf",
      "title": "PEAK/SHELF MORPH",
      "intent": "Operator-style Peak/Shelf Morph behavior: frequency means different things as the shelf frame turns.",
      "bias": "Use as the calibration seed for shelf fundamentals before adding character rows.",
      "move": "low-pass / mid-shelf / high-pass continuum",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 200.0,
        "tiltDb": 14.0,
        "canyonDepth": 20.0,
        "qCrank": 0.62,
        "morphSpread": 0.78,
        "density": 0.62
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_peak_shelf_morph",
        "family": "root_shelf",
        "title": "PEAK/SHELF MORPH",
        "intent": "Operator-style Peak/Shelf Morph behavior: frequency means different things as the shelf frame turns.",
        "bias": "Use as the calibration seed for shelf fundamentals before adding character rows.",
        "move": "low-pass / mid-shelf / high-pass continuum",
        "anchor_hz": 200.0,
        "anchor_gain_db": 3.8,
        "tilt_db": 14.0,
        "canyon_depth": 20.0,
        "q_crank": 0.62,
        "morph_spread": 0.78,
        "density": 0.62,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 200.0,
            "gain_db": 2.6,
            "bw_oct": 3.2,
            "zero_offset_oct": -1.6,
            "morph_oct": 0.25,
            "zero_morph_oct": 0.35,
            "zero_secondary_oct": -0.1,
            "q_weight": 0.55
          },
          {
            "role": "dark_shelf",
            "fc_hz": 390.0,
            "gain_db": -7.0,
            "bw_oct": 2.0,
            "zero_offset_oct": -1.0,
            "morph_oct": 1.4,
            "zero_morph_oct": 0.95,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.65
          },
          {
            "role": "mid_shelf",
            "fc_hz": 780.0,
            "gain_db": 3.0,
            "bw_oct": 1.8,
            "zero_offset_oct": 0.25,
            "morph_oct": 0.85,
            "zero_morph_oct": -0.35,
            "zero_secondary_oct": 0.12,
            "q_weight": 0.85
          },
          {
            "role": "peak_hinge",
            "fc_hz": 2220.0,
            "gain_db": 4.5,
            "bw_oct": 0.85,
            "zero_offset_oct": -0.18,
            "morph_oct": 0.35,
            "zero_morph_oct": 0.1,
            "zero_secondary_oct": -0.18,
            "q_weight": 1.0
          },
          {
            "role": "bright_shelf",
            "fc_hz": 4130.0,
            "gain_db": 2.2,
            "bw_oct": 1.7,
            "zero_offset_oct": 0.92,
            "morph_oct": -0.55,
            "zero_morph_oct": -1.1,
            "zero_secondary_oct": 0.15,
            "q_weight": 0.72
          },
          {
            "role": "air_cap",
            "fc_hz": 8250.0,
            "gain_db": -4.0,
            "bw_oct": 1.35,
            "zero_offset_oct": 0.8,
            "morph_oct": -0.9,
            "zero_morph_oct": -0.85,
            "zero_secondary_oct": 0.18,
            "q_weight": 0.42
          }
        ]
      },
      "roles": [
        "anchor",
        "dark_shelf",
        "mid_shelf",
        "peak_hinge",
        "bright_shelf",
        "air_cap"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 200.0,
            "poleR": 0.9574762,
            "zeroHz": 65.9754,
            "zeroR": 0.5022222,
            "gain": 0.025
          },
          {
            "role": "dark_shelf",
            "poleHz": 390.0,
            "poleR": 0.5511111,
            "zeroHz": 195.0,
            "zeroR": 0.8733333,
            "gain": 3.75
          },
          {
            "role": "mid_shelf",
            "poleHz": 780.0,
            "poleR": 0.9199427,
            "zeroHz": 927.5815,
            "zeroR": 0.5022222,
            "gain": 0.0806007
          },
          {
            "role": "peak_hinge",
            "poleHz": 2220.0,
            "poleR": 0.8987762,
            "zeroHz": 1959.6007,
            "zeroR": 0.5022222,
            "gain": 0.4159114
          },
          {
            "role": "bright_shelf",
            "poleHz": 4130.0,
            "poleR": 0.6607139,
            "zeroHz": 7814.4362,
            "zeroR": 0.5022222,
            "gain": 0.4204556
          },
          {
            "role": "air_cap",
            "poleHz": 8250.0,
            "poleR": 0.5511111,
            "zeroHz": 14364.0843,
            "zeroR": 0.8733333,
            "gain": 0.3529452
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 228.9448,
            "poleR": 0.9574762,
            "zeroHz": 79.7192,
            "zeroR": 0.5022222,
            "gain": 0.025
          },
          {
            "role": "dark_shelf",
            "poleHz": 831.3605,
            "poleR": 0.5511111,
            "zeroHz": 325.9101,
            "zeroR": 0.8733333,
            "gain": 3.75
          },
          {
            "role": "mid_shelf",
            "poleHz": 1235.03,
            "poleR": 0.9199427,
            "zeroHz": 767.6635,
            "zeroR": 0.5022222,
            "gain": 0.166754
          },
          {
            "role": "peak_hinge",
            "poleHz": 2682.4656,
            "poleR": 0.8987762,
            "zeroHz": 2068.4638,
            "zeroR": 0.5022222,
            "gain": 0.5777829
          },
          {
            "role": "bright_shelf",
            "poleHz": 3067.6668,
            "poleR": 0.6607139,
            "zeroHz": 4311.3563,
            "zeroR": 0.5022222,
            "gain": 0.5684767
          },
          {
            "role": "air_cap",
            "poleHz": 5071.4353,
            "poleR": 0.5511111,
            "zeroHz": 9071.8332,
            "zeroR": 0.8733333,
            "gain": 0.3496609
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 200.0,
            "poleR": 0.9999,
            "zeroHz": 61.5572,
            "zeroR": 0.5226822,
            "gain": 0.025
          },
          {
            "role": "dark_shelf",
            "poleHz": 390.0,
            "poleR": 0.5914111,
            "zeroHz": 195.0,
            "zeroR": 0.8813933,
            "gain": 3.75
          },
          {
            "role": "mid_shelf",
            "poleHz": 780.0,
            "poleR": 0.9620802,
            "zeroHz": 1008.0352,
            "zeroR": 0.5338422,
            "gain": 0.071602
          },
          {
            "role": "peak_hinge",
            "poleHz": 2220.0,
            "poleR": 0.961473,
            "zeroHz": 1729.7454,
            "zeroR": 0.5394222,
            "gain": 0.4841286
          },
          {
            "role": "bright_shelf",
            "poleHz": 4130.0,
            "poleR": 0.8121266,
            "zeroHz": 8670.6598,
            "zeroR": 0.5290062,
            "gain": 0.3478449
          },
          {
            "role": "air_cap",
            "poleHz": 8250.0,
            "poleR": 0.5771511,
            "zeroHz": 16272.8396,
            "zeroR": 0.8785413,
            "gain": 0.3202122
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 228.9448,
            "poleR": 0.9999,
            "zeroHz": 74.3807,
            "zeroR": 0.5226822,
            "gain": 0.025
          },
          {
            "role": "dark_shelf",
            "poleHz": 831.3605,
            "poleR": 0.5914111,
            "zeroHz": 325.9101,
            "zeroR": 0.8813933,
            "gain": 3.75
          },
          {
            "role": "mid_shelf",
            "poleHz": 1235.03,
            "poleR": 0.9620802,
            "zeroHz": 834.2467,
            "zeroR": 0.5338422,
            "gain": 0.1731158
          },
          {
            "role": "peak_hinge",
            "poleHz": 2682.4656,
            "poleR": 0.961473,
            "zeroHz": 1825.8392,
            "zeroR": 0.5394222,
            "gain": 0.6879775
          },
          {
            "role": "bright_shelf",
            "poleHz": 3067.6668,
            "poleR": 0.8121266,
            "zeroHz": 4783.7493,
            "zeroR": 0.5290062,
            "gain": 0.4405706
          },
          {
            "role": "air_cap",
            "poleHz": 5071.4353,
            "poleR": 0.5771511,
            "zeroHz": 10277.3337,
            "zeroR": 0.8785413,
            "gain": 0.2828503
          }
        ]
      }
    },
    {
      "id": "root_dark_cliff_frame",
      "family": "root_shelf",
      "title": "DARK CLIFF FRAME",
      "intent": "The broad keep/kill frame first; character rows sit inside a descending wall.",
      "bias": "Use when the top must fall into the mouth/bite area instead of opening upward.",
      "move": "hard descending cliff with character rows inside",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 134.0,
        "tiltDb": -18.0,
        "canyonDepth": 30.0,
        "qCrank": 0.7,
        "morphSpread": 0.82,
        "density": 0.72
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_dark_cliff_frame",
        "family": "root_shelf",
        "title": "DARK CLIFF FRAME",
        "intent": "The broad keep/kill frame first; character rows sit inside a descending wall.",
        "bias": "Use when the top must fall into the mouth/bite area instead of opening upward.",
        "move": "hard descending cliff with character rows inside",
        "anchor_hz": 134.0,
        "anchor_gain_db": 4.0,
        "tilt_db": -18.0,
        "canyon_depth": 30.0,
        "q_crank": 0.7,
        "morph_spread": 0.82,
        "density": 0.72,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 134.0,
            "gain_db": 3.0,
            "bw_oct": 3.4,
            "zero_offset_oct": -1.15,
            "morph_oct": 0.15,
            "zero_morph_oct": 0.3,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.45
          },
          {
            "role": "cliff",
            "fc_hz": 390.0,
            "gain_db": -10.0,
            "bw_oct": 1.4,
            "zero_offset_oct": -0.65,
            "morph_oct": 1.0,
            "zero_morph_oct": 0.8,
            "zero_secondary_oct": 0.25,
            "q_weight": 0.8
          },
          {
            "role": "remote_cut",
            "fc_hz": 780.0,
            "gain_db": -8.2,
            "bw_oct": 0.74,
            "zero_offset_oct": -1.55,
            "morph_oct": 0.95,
            "zero_morph_oct": 1.25,
            "zero_secondary_oct": 0.35,
            "q_weight": 0.92
          },
          {
            "role": "mouth_bite",
            "fc_hz": 2180.0,
            "gain_db": 3.2,
            "bw_oct": 0.86,
            "zero_offset_oct": 0.3,
            "morph_oct": -0.35,
            "zero_morph_oct": -0.45,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.88
          },
          {
            "role": "tear_cut",
            "fc_hz": 4130.0,
            "gain_db": -8.6,
            "bw_oct": 0.7,
            "zero_offset_oct": -0.92,
            "morph_oct": -0.85,
            "zero_morph_oct": 0.95,
            "zero_secondary_oct": 0.22,
            "q_weight": 0.76
          },
          {
            "role": "air_kill",
            "fc_hz": 7200.0,
            "gain_db": -13.4,
            "bw_oct": 0.9,
            "zero_offset_oct": -0.18,
            "morph_oct": -1.3,
            "zero_morph_oct": -0.65,
            "zero_secondary_oct": 0.12,
            "q_weight": 0.5
          }
        ]
      },
      "roles": [
        "anchor",
        "cliff",
        "remote_cut",
        "mouth_bite",
        "tear_cut",
        "air_kill"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 134.0,
            "poleR": 0.9687998,
            "zeroHz": 60.3838,
            "zeroR": 0.5633333,
            "gain": 0.025
          },
          {
            "role": "cliff",
            "poleHz": 390.0,
            "poleR": 0.4816667,
            "zeroHz": 248.5393,
            "zeroR": 0.94,
            "gain": 3.75
          },
          {
            "role": "remote_cut",
            "poleHz": 780.0,
            "poleR": 0.4816667,
            "zeroHz": 266.3779,
            "zeroR": 0.94,
            "gain": 3.75
          },
          {
            "role": "mouth_bite",
            "poleHz": 2180.0,
            "poleR": 0.8993641,
            "zeroHz": 2683.8948,
            "zeroR": 0.5633333,
            "gain": 0.4066803
          },
          {
            "role": "tear_cut",
            "poleHz": 4130.0,
            "poleR": 0.4816667,
            "zeroHz": 2182.7423,
            "zeroR": 0.94,
            "gain": 3.75
          },
          {
            "role": "air_kill",
            "poleHz": 7200.0,
            "poleR": 0.4816667,
            "zeroHz": 6355.4616,
            "zeroR": 0.94,
            "gain": 0.9361543
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 145.9256,
            "poleR": 0.9687998,
            "zeroHz": 71.61,
            "zeroR": 0.5633333,
            "gain": 0.025
          },
          {
            "role": "cliff",
            "poleHz": 688.5083,
            "poleR": 0.4816667,
            "zeroHz": 391.6253,
            "zeroR": 0.94,
            "gain": 3.75
          },
          {
            "role": "remote_cut",
            "poleHz": 1338.434,
            "poleR": 0.4816667,
            "zeroHz": 542.0681,
            "zeroR": 0.94,
            "gain": 3.75
          },
          {
            "role": "mouth_bite",
            "poleHz": 1786.738,
            "poleR": 0.8993641,
            "zeroHz": 2078.1908,
            "zeroR": 0.5633333,
            "gain": 0.3315747
          },
          {
            "role": "tear_cut",
            "poleHz": 2547.6053,
            "poleR": 0.4816667,
            "zeroHz": 3745.4571,
            "zeroR": 0.94,
            "gain": 1.0413829
          },
          {
            "role": "air_kill",
            "poleHz": 3439.0186,
            "poleR": 0.4816667,
            "zeroHz": 4392.3618,
            "zeroR": 0.94,
            "gain": 0.9090062
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 134.0,
            "poleR": 0.9999,
            "zeroHz": 60.3838,
            "zeroR": 0.5822333,
            "gain": 0.025
          },
          {
            "role": "cliff",
            "poleHz": 390.0,
            "poleR": 0.5376667,
            "zeroHz": 295.5647,
            "zeroR": 0.9512,
            "gain": 3.75
          },
          {
            "role": "remote_cut",
            "poleHz": 780.0,
            "poleR": 0.5460667,
            "zeroHz": 339.5147,
            "zeroR": 0.95288,
            "gain": 3.75
          },
          {
            "role": "mouth_bite",
            "poleHz": 2180.0,
            "poleR": 0.9612942,
            "zeroHz": 2683.8948,
            "zeroR": 0.6002933,
            "gain": 0.4389905
          },
          {
            "role": "tear_cut",
            "poleHz": 4130.0,
            "poleR": 0.5348667,
            "zeroHz": 2542.3132,
            "zeroR": 0.95064,
            "gain": 2.787857
          },
          {
            "role": "air_kill",
            "poleHz": 7200.0,
            "poleR": 0.5166667,
            "zeroHz": 6906.7017,
            "zeroR": 0.947,
            "gain": 0.8071371
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 145.9256,
            "poleR": 0.9999,
            "zeroHz": 71.61,
            "zeroR": 0.5822333,
            "gain": 0.025
          },
          {
            "role": "cliff",
            "poleHz": 688.5083,
            "poleR": 0.5376667,
            "zeroHz": 465.7236,
            "zeroR": 0.9512,
            "gain": 3.75
          },
          {
            "role": "remote_cut",
            "poleHz": 1338.434,
            "poleR": 0.5460667,
            "zeroHz": 690.8987,
            "zeroR": 0.95288,
            "gain": 3.75
          },
          {
            "role": "mouth_bite",
            "poleHz": 1786.738,
            "poleR": 0.9612942,
            "zeroHz": 2078.1908,
            "zeroR": 0.6002933,
            "gain": 0.3551965
          },
          {
            "role": "tear_cut",
            "poleHz": 2547.6053,
            "poleR": 0.5348667,
            "zeroHz": 4362.4596,
            "zeroR": 0.95064,
            "gain": 0.6751552
          },
          {
            "role": "air_kill",
            "poleHz": 3439.0186,
            "poleR": 0.5166667,
            "zeroHz": 4773.3327,
            "zeroR": 0.947,
            "gain": 0.7258241
          }
        ]
      }
    },
    {
      "id": "root_bright_shelf_frame",
      "family": "root_shelf",
      "title": "BRIGHT SHELF FRAME",
      "intent": "A broad rising frame, with air restraint so it reads as shelf rather than fizz.",
      "bias": "Use for bright shelf fundamentals before adding remote violence.",
      "move": "rising shelf with restrained air cap",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 320.0,
        "tiltDb": 18.0,
        "canyonDepth": 18.0,
        "qCrank": 0.54,
        "morphSpread": 0.72,
        "density": 0.58
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_bright_shelf_frame",
        "family": "root_shelf",
        "title": "BRIGHT SHELF FRAME",
        "intent": "A broad rising frame, with air restraint so it reads as shelf rather than fizz.",
        "bias": "Use for bright shelf fundamentals before adding remote violence.",
        "move": "rising shelf with restrained air cap",
        "anchor_hz": 320.0,
        "anchor_gain_db": 3.2,
        "tilt_db": 18.0,
        "canyon_depth": 18.0,
        "q_crank": 0.54,
        "morph_spread": 0.72,
        "density": 0.58,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 320.0,
            "gain_db": 2.2,
            "bw_oct": 2.8,
            "zero_offset_oct": -1.3,
            "morph_oct": 0.3,
            "zero_morph_oct": 0.25,
            "zero_secondary_oct": -0.1,
            "q_weight": 0.45
          },
          {
            "role": "low_keep",
            "fc_hz": 545.0,
            "gain_db": -3.0,
            "bw_oct": 2.2,
            "zero_offset_oct": -0.75,
            "morph_oct": 0.35,
            "zero_morph_oct": 0.2,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.45
          },
          {
            "role": "shelf_rise",
            "fc_hz": 1200.0,
            "gain_db": 2.8,
            "bw_oct": 1.9,
            "zero_offset_oct": 0.45,
            "morph_oct": 0.65,
            "zero_morph_oct": -0.2,
            "zero_secondary_oct": 0.05,
            "q_weight": 0.72
          },
          {
            "role": "bite_peak",
            "fc_hz": 2220.0,
            "gain_db": 4.0,
            "bw_oct": 0.95,
            "zero_offset_oct": 0.18,
            "morph_oct": 0.45,
            "zero_morph_oct": -0.12,
            "zero_secondary_oct": -0.15,
            "q_weight": 0.95
          },
          {
            "role": "tear_shelf",
            "fc_hz": 4440.0,
            "gain_db": 2.5,
            "bw_oct": 1.35,
            "zero_offset_oct": 0.65,
            "morph_oct": -0.25,
            "zero_morph_oct": -0.6,
            "zero_secondary_oct": 0.12,
            "q_weight": 0.65
          },
          {
            "role": "air_restraint",
            "fc_hz": 9650.0,
            "gain_db": -4.8,
            "bw_oct": 0.95,
            "zero_offset_oct": 0.55,
            "morph_oct": -0.55,
            "zero_morph_oct": -0.7,
            "zero_secondary_oct": 0.35,
            "q_weight": 0.52
          }
        ]
      },
      "roles": [
        "anchor",
        "low_keep",
        "shelf_rise",
        "bite_peak",
        "tear_shelf",
        "air_restraint"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 320.0,
            "poleR": 0.9434939,
            "zeroHz": 129.9604,
            "zeroR": 0.49,
            "gain": 0.025
          },
          {
            "role": "low_keep",
            "poleHz": 545.0,
            "poleR": 0.565,
            "zeroHz": 324.0589,
            "zeroR": 0.86,
            "gain": 3.75
          },
          {
            "role": "shelf_rise",
            "poleHz": 1200.0,
            "poleR": 0.8724168,
            "zeroHz": 1639.2483,
            "zeroR": 0.49,
            "gain": 0.1655951
          },
          {
            "role": "bite_peak",
            "poleHz": 2220.0,
            "poleR": 0.8871826,
            "zeroHz": 2515.0022,
            "zeroR": 0.49,
            "gain": 0.3674984
          },
          {
            "role": "tear_shelf",
            "poleHz": 4440.0,
            "poleR": 0.7071815,
            "zeroHz": 6967.1068,
            "zeroR": 0.49,
            "gain": 0.530118
          },
          {
            "role": "air_restraint",
            "poleHz": 9650.0,
            "poleR": 0.565,
            "zeroHz": 14128.427,
            "zeroR": 0.86,
            "gain": 0.4555186
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 371.6828,
            "poleR": 0.9434939,
            "zeroHz": 147.23,
            "zeroR": 0.49,
            "gain": 0.0252107
          },
          {
            "role": "low_keep",
            "poleHz": 649.017,
            "poleR": 0.565,
            "zeroHz": 358.0736,
            "zeroR": 0.86,
            "gain": 3.75
          },
          {
            "role": "shelf_rise",
            "poleHz": 1659.8288,
            "poleR": 0.8724168,
            "zeroHz": 1483.5303,
            "zeroR": 0.49,
            "gain": 0.2712849
          },
          {
            "role": "bite_peak",
            "poleHz": 2778.9881,
            "poleR": 0.8871826,
            "zeroHz": 2368.8054,
            "zeroR": 0.49,
            "gain": 0.5662019
          },
          {
            "role": "tear_shelf",
            "poleHz": 3919.2013,
            "poleR": 0.7071815,
            "zeroHz": 5164.253,
            "zeroR": 0.49,
            "gain": 0.6173918
          },
          {
            "role": "air_restraint",
            "poleHz": 7333.6374,
            "poleR": 0.565,
            "zeroHz": 9962.6459,
            "zeroR": 0.86,
            "gain": 0.4951649
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 320.0,
            "poleR": 0.9999,
            "zeroHz": 121.2573,
            "zeroR": 0.50458,
            "gain": 0.025
          },
          {
            "role": "low_keep",
            "poleHz": 545.0,
            "poleR": 0.5893,
            "zeroHz": 324.0589,
            "zeroR": 0.86486,
            "gain": 3.75
          },
          {
            "role": "shelf_rise",
            "poleHz": 1200.0,
            "poleR": 0.9219823,
            "zeroHz": 1697.0563,
            "zeroR": 0.513328,
            "gain": 0.1467283
          },
          {
            "role": "bite_peak",
            "poleHz": 2220.0,
            "poleR": 0.9450066,
            "zeroHz": 2266.6469,
            "zeroR": 0.52078,
            "gain": 0.4100707
          },
          {
            "role": "tear_shelf",
            "poleHz": 4440.0,
            "poleR": 0.8099257,
            "zeroHz": 7571.3978,
            "zeroR": 0.51106,
            "gain": 0.4757929
          },
          {
            "role": "air_restraint",
            "poleHz": 9650.0,
            "poleR": 0.59308,
            "zeroHz": 18007.5367,
            "zeroR": 0.865616,
            "gain": 0.3878004
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 371.6828,
            "poleR": 0.9999,
            "zeroHz": 137.3705,
            "zeroR": 0.50458,
            "gain": 0.025
          },
          {
            "role": "low_keep",
            "poleHz": 649.017,
            "poleR": 0.5893,
            "zeroHz": 358.0736,
            "zeroR": 0.86486,
            "gain": 3.75
          },
          {
            "role": "shelf_rise",
            "poleHz": 1659.8288,
            "poleR": 0.9219823,
            "zeroHz": 1535.8469,
            "zeroR": 0.513328,
            "gain": 0.2664592
          },
          {
            "role": "bite_peak",
            "poleHz": 2778.9881,
            "poleR": 0.9450066,
            "zeroHz": 2134.887,
            "zeroR": 0.52078,
            "gain": 0.6497288
          },
          {
            "role": "tear_shelf",
            "poleHz": 3919.2013,
            "poleR": 0.8099257,
            "zeroHz": 5612.1738,
            "zeroR": 0.51106,
            "gain": 0.5533109
          },
          {
            "role": "air_restraint",
            "poleHz": 7333.6374,
            "poleR": 0.59308,
            "zeroHz": 12697.9962,
            "zeroR": 0.865616,
            "gain": 0.3546961
          }
        ]
      }
    },
    {
      "id": "root_remote_cut_bp",
      "family": "root_bp",
      "title": "REMOTE-CUT BP",
      "intent": "The zeros are the actors; peaks hold a window while remote cuts move separately.",
      "bias": "Use when polite band-pass laws feel too static or too all-pole.",
      "move": "band-pass body with cuts walking away",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 365.0,
        "tiltDb": 4.0,
        "canyonDepth": 32.0,
        "qCrank": 0.82,
        "morphSpread": 0.92,
        "density": 0.82
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_remote_cut_bp",
        "family": "root_bp",
        "title": "REMOTE-CUT BP",
        "intent": "The zeros are the actors; peaks hold a window while remote cuts move separately.",
        "bias": "Use when polite band-pass laws feel too static or too all-pole.",
        "move": "band-pass body with cuts walking away",
        "anchor_hz": 365.0,
        "anchor_gain_db": 4.0,
        "tilt_db": 4.0,
        "canyon_depth": 32.0,
        "q_crank": 0.82,
        "morph_spread": 0.92,
        "density": 0.82,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 365.0,
            "gain_db": 2.8,
            "bw_oct": 2.4,
            "zero_offset_oct": -1.1,
            "morph_oct": 0.25,
            "zero_morph_oct": 0.2,
            "zero_secondary_oct": -0.2,
            "q_weight": 0.55
          },
          {
            "role": "lower_bp_wall",
            "fc_hz": 780.0,
            "gain_db": -7.2,
            "bw_oct": 0.72,
            "zero_offset_oct": -1.8,
            "morph_oct": 0.95,
            "zero_morph_oct": 1.7,
            "zero_secondary_oct": 0.4,
            "q_weight": 1.0
          },
          {
            "role": "mouth_peak",
            "fc_hz": 1200.0,
            "gain_db": 4.8,
            "bw_oct": 0.78,
            "zero_offset_oct": 0.22,
            "morph_oct": 0.55,
            "zero_morph_oct": -0.4,
            "zero_secondary_oct": -0.12,
            "q_weight": 0.95
          },
          {
            "role": "bite_peak",
            "fc_hz": 2220.0,
            "gain_db": 3.8,
            "bw_oct": 0.82,
            "zero_offset_oct": -0.15,
            "morph_oct": 0.35,
            "zero_morph_oct": -0.75,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.88
          },
          {
            "role": "remote_canyon",
            "fc_hz": 4440.0,
            "gain_db": -10.5,
            "bw_oct": 0.55,
            "zero_offset_oct": -2.3,
            "morph_oct": -0.65,
            "zero_morph_oct": 2.15,
            "zero_secondary_oct": 0.55,
            "q_weight": 1.0
          },
          {
            "role": "air_kill",
            "fc_hz": 8250.0,
            "gain_db": -7.5,
            "bw_oct": 0.9,
            "zero_offset_oct": 0.85,
            "morph_oct": -0.85,
            "zero_morph_oct": -1.3,
            "zero_secondary_oct": 0.3,
            "q_weight": 0.7
          }
        ]
      },
      "roles": [
        "anchor",
        "lower_bp_wall",
        "mouth_peak",
        "bite_peak",
        "remote_canyon",
        "air_kill"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 365.0,
            "poleR": 0.9468045,
            "zeroHz": 170.2785,
            "zeroR": 0.5755556,
            "gain": 0.0337367
          },
          {
            "role": "lower_bp_wall",
            "poleHz": 780.0,
            "poleR": 0.4677778,
            "zeroHz": 223.9962,
            "zeroR": 0.9533333,
            "gain": 3.75
          },
          {
            "role": "mouth_peak",
            "poleHz": 1200.0,
            "poleR": 0.9485543,
            "zeroHz": 1397.6803,
            "zeroR": 0.5755556,
            "gain": 0.1811246
          },
          {
            "role": "bite_peak",
            "poleHz": 2220.0,
            "poleR": 0.9022606,
            "zeroHz": 2000.776,
            "zeroR": 0.5755556,
            "gain": 0.5157065
          },
          {
            "role": "remote_canyon",
            "poleHz": 4440.0,
            "poleR": 0.4677778,
            "zeroHz": 901.6002,
            "zeroR": 0.9533333,
            "gain": 3.75
          },
          {
            "role": "air_kill",
            "poleHz": 8250.0,
            "poleR": 0.4677778,
            "zeroHz": 14870.6326,
            "zeroR": 0.9533333,
            "gain": 0.3005081
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 428.0848,
            "poleR": 0.9468045,
            "zeroHz": 193.4414,
            "zeroR": 0.5755556,
            "gain": 0.0404907
          },
          {
            "role": "lower_bp_wall",
            "poleHz": 1429.5351,
            "poleR": 0.4677778,
            "zeroHz": 662.2951,
            "zeroR": 0.9533333,
            "gain": 3.75
          },
          {
            "role": "mouth_peak",
            "poleHz": 1704.1288,
            "poleR": 0.9485543,
            "zeroHz": 1083.0009,
            "zeroR": 0.5755556,
            "gain": 0.3718673
          },
          {
            "role": "bite_peak",
            "poleHz": 2775.1383,
            "poleR": 0.9022606,
            "zeroHz": 1240.1887,
            "zeroR": 0.5755556,
            "gain": 0.918153
          },
          {
            "role": "remote_canyon",
            "poleHz": 2933.3713,
            "poleR": 0.4677778,
            "zeroHz": 3551.823,
            "zeroR": 0.9533333,
            "gain": 1.2640063
          },
          {
            "role": "air_kill",
            "poleHz": 4797.8702,
            "poleR": 0.4677778,
            "zeroHz": 6490.7902,
            "zeroR": 0.9533333,
            "gain": 0.5769758
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 365.0,
            "poleR": 0.9999,
            "zeroHz": 148.2361,
            "zeroR": 0.6026156,
            "gain": 0.025
          },
          {
            "role": "lower_bp_wall",
            "poleHz": 780.0,
            "poleR": 0.5497778,
            "zeroHz": 295.5647,
            "zeroR": 0.9697333,
            "gain": 3.75
          },
          {
            "role": "mouth_peak",
            "poleHz": 1200.0,
            "poleR": 0.9885526,
            "zeroHz": 1286.1282,
            "zeroR": 0.6222956,
            "gain": 0.2177738
          },
          {
            "role": "bite_peak",
            "poleHz": 2220.0,
            "poleR": 0.9727172,
            "zeroHz": 2000.776,
            "zeroR": 0.6188516,
            "gain": 0.5912505
          },
          {
            "role": "remote_canyon",
            "poleHz": 4440.0,
            "poleR": 0.5497778,
            "zeroHz": 1320.0199,
            "zeroR": 0.9697333,
            "gain": 3.75
          },
          {
            "role": "air_kill",
            "poleHz": 8250.0,
            "poleR": 0.5251778,
            "zeroHz": 18307.8963,
            "zeroR": 0.9648133,
            "gain": 0.267384
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 428.0848,
            "poleR": 0.9999,
            "zeroHz": 168.4005,
            "zeroR": 0.6026156,
            "gain": 0.029926
          },
          {
            "role": "lower_bp_wall",
            "poleHz": 1429.5351,
            "poleR": 0.5497778,
            "zeroHz": 873.9036,
            "zeroR": 0.9697333,
            "gain": 3.75
          },
          {
            "role": "mouth_peak",
            "poleHz": 1704.1288,
            "poleR": 0.9885526,
            "zeroHz": 996.564,
            "zeroR": 0.6222956,
            "gain": 0.4661715
          },
          {
            "role": "bite_peak",
            "poleHz": 2775.1383,
            "poleR": 0.9727172,
            "zeroHz": 1240.1887,
            "zeroR": 0.6188516,
            "gain": 1.126882
          },
          {
            "role": "remote_canyon",
            "poleHz": 2933.3713,
            "poleR": 0.5497778,
            "zeroHz": 5200.1732,
            "zeroR": 0.9697333,
            "gain": 0.503859
          },
          {
            "role": "air_kill",
            "poleHz": 4797.8702,
            "poleR": 0.5251778,
            "zeroHz": 7991.1001,
            "zeroR": 0.9648133,
            "gain": 0.3769415
          }
        ]
      }
    },
    {
      "id": "root_mouth_window",
      "family": "root_mouth",
      "title": "MOUTH WINDOW",
      "intent": "Keep the body legible while one or two mouth rows sweep hard.",
      "bias": "Use for OOH/AAH/EEE-style motion without copying any reference row.",
      "move": "vowel window / bite glide",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 390.0,
        "tiltDb": 8.0,
        "canyonDepth": 24.0,
        "qCrank": 0.74,
        "morphSpread": 0.7,
        "density": 0.78
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_mouth_window",
        "family": "root_mouth",
        "title": "MOUTH WINDOW",
        "intent": "Keep the body legible while one or two mouth rows sweep hard.",
        "bias": "Use for OOH/AAH/EEE-style motion without copying any reference row.",
        "move": "vowel window / bite glide",
        "anchor_hz": 390.0,
        "anchor_gain_db": 4.0,
        "tilt_db": 8.0,
        "canyon_depth": 24.0,
        "q_crank": 0.74,
        "morph_spread": 0.7,
        "density": 0.78,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 390.0,
            "gain_db": 2.6,
            "bw_oct": 2.2,
            "zero_offset_oct": -0.9,
            "morph_oct": -0.2,
            "zero_morph_oct": 0.25,
            "zero_secondary_oct": -0.12,
            "q_weight": 0.55
          },
          {
            "role": "mouth_f1",
            "fc_hz": 780.0,
            "gain_db": 5.8,
            "bw_oct": 0.95,
            "zero_offset_oct": 0.06,
            "morph_oct": -0.55,
            "zero_morph_oct": 0.2,
            "zero_secondary_oct": 0.0,
            "q_weight": 1.0
          },
          {
            "role": "mouth_f2",
            "fc_hz": 1200.0,
            "gain_db": 4.8,
            "bw_oct": 0.88,
            "zero_offset_oct": 0.18,
            "morph_oct": 0.85,
            "zero_morph_oct": -0.2,
            "zero_secondary_oct": 0.0,
            "q_weight": 1.0
          },
          {
            "role": "bite",
            "fc_hz": 2220.0,
            "gain_db": 3.4,
            "bw_oct": 0.82,
            "zero_offset_oct": -0.1,
            "morph_oct": 0.62,
            "zero_morph_oct": -0.45,
            "zero_secondary_oct": 0.12,
            "q_weight": 0.92
          },
          {
            "role": "tear_canyon",
            "fc_hz": 3790.0,
            "gain_db": -6.2,
            "bw_oct": 0.7,
            "zero_offset_oct": -0.75,
            "morph_oct": -0.35,
            "zero_morph_oct": 0.8,
            "zero_secondary_oct": 0.22,
            "q_weight": 0.72
          },
          {
            "role": "air_kill",
            "fc_hz": 8875.0,
            "gain_db": -5.2,
            "bw_oct": 1.05,
            "zero_offset_oct": 0.65,
            "morph_oct": -0.7,
            "zero_morph_oct": -0.7,
            "zero_secondary_oct": 0.2,
            "q_weight": 0.55
          }
        ]
      },
      "roles": [
        "anchor",
        "mouth_f1",
        "mouth_f2",
        "bite",
        "tear_canyon",
        "air_kill"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 390.0,
            "poleR": 0.9487583,
            "zeroHz": 208.9958,
            "zeroR": 0.5266667,
            "gain": 0.0283034
          },
          {
            "role": "mouth_f1",
            "poleHz": 780.0,
            "poleR": 0.9588139,
            "zeroHz": 813.1233,
            "zeroR": 0.5266667,
            "gain": 0.0719577
          },
          {
            "role": "mouth_f2",
            "poleHz": 1200.0,
            "poleR": 0.9419672,
            "zeroHz": 1359.4607,
            "zeroR": 0.5266667,
            "gain": 0.153951
          },
          {
            "role": "bite",
            "poleHz": 2220.0,
            "poleR": 0.9022606,
            "zeroHz": 2071.3332,
            "zeroR": 0.5266667,
            "gain": 0.4375793
          },
          {
            "role": "tear_canyon",
            "poleHz": 3790.0,
            "poleR": 0.5233333,
            "zeroHz": 2253.5475,
            "zeroR": 0.9,
            "gain": 3.2745427
          },
          {
            "role": "air_kill",
            "poleHz": 8875.0,
            "poleR": 0.5233333,
            "zeroHz": 13926.3677,
            "zeroR": 0.9,
            "gain": 0.3842006
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 353.9325,
            "poleR": 0.9487583,
            "zeroHz": 235.9488,
            "zeroR": 0.5266667,
            "gain": 0.0253547
          },
          {
            "role": "mouth_f1",
            "poleHz": 597.3076,
            "poleR": 0.9588139,
            "zeroHz": 895.9847,
            "zeroR": 0.5266667,
            "gain": 0.044858
          },
          {
            "role": "mouth_f2",
            "poleHz": 1812.5671,
            "poleR": 0.9419672,
            "zeroHz": 1233.7366,
            "zeroR": 0.5266667,
            "gain": 0.3386405
          },
          {
            "role": "bite",
            "poleHz": 2999.1625,
            "poleR": 0.9022606,
            "zeroHz": 1665.0433,
            "zeroR": 0.5266667,
            "gain": 0.8237478
          },
          {
            "role": "tear_canyon",
            "poleHz": 3198.0619,
            "poleR": 0.5233333,
            "zeroHz": 3322.3357,
            "zeroR": 0.9,
            "gain": 1.389723
          },
          {
            "role": "air_kill",
            "poleHz": 6319.2227,
            "poleR": 0.5233333,
            "zeroHz": 9915.9234,
            "zeroR": 0.9,
            "gain": 0.3900273
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 390.0,
            "poleR": 0.9999,
            "zeroHz": 192.3154,
            "zeroR": 0.5510867,
            "gain": 0.025
          },
          {
            "role": "mouth_f1",
            "poleHz": 780.0,
            "poleR": 0.9892176,
            "zeroHz": 813.1233,
            "zeroR": 0.5710667,
            "gain": 0.0808667
          },
          {
            "role": "mouth_f2",
            "poleHz": 1200.0,
            "poleR": 0.9848375,
            "zeroHz": 1359.4607,
            "zeroR": 0.5710667,
            "gain": 0.1742945
          },
          {
            "role": "bite",
            "poleHz": 2220.0,
            "poleR": 0.9687335,
            "zeroHz": 2250.99,
            "zeroR": 0.5675147,
            "gain": 0.4726735
          },
          {
            "role": "tear_canyon",
            "poleHz": 3790.0,
            "poleR": 0.5766133,
            "zeroHz": 2624.7824,
            "zeroR": 0.910656,
            "gain": 2.3047756
          },
          {
            "role": "air_kill",
            "poleHz": 8875.0,
            "poleR": 0.5640333,
            "zeroHz": 15997.1957,
            "zeroR": 0.90814,
            "gain": 0.3448458
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 353.9325,
            "poleR": 0.9999,
            "zeroHz": 217.1172,
            "zeroR": 0.5510867,
            "gain": 0.025
          },
          {
            "role": "mouth_f1",
            "poleHz": 597.3076,
            "poleR": 0.9892176,
            "zeroHz": 895.9847,
            "zeroR": 0.5710667,
            "gain": 0.0471873
          },
          {
            "role": "mouth_f2",
            "poleHz": 1812.5671,
            "poleR": 0.9848375,
            "zeroHz": 1233.7366,
            "zeroR": 0.5710667,
            "gain": 0.4038365
          },
          {
            "role": "bite",
            "poleHz": 2999.1625,
            "poleR": 0.9687335,
            "zeroHz": 1809.4606,
            "zeroR": 0.5675147,
            "gain": 0.9459332
          },
          {
            "role": "tear_canyon",
            "poleHz": 3198.0619,
            "poleR": 0.5766133,
            "zeroHz": 3869.636,
            "zeroR": 0.910656,
            "gain": 0.9398031
          },
          {
            "role": "air_kill",
            "poleHz": 6319.2227,
            "poleR": 0.5640333,
            "zeroHz": 11390.4048,
            "zeroR": 0.90814,
            "gain": 0.3157475
          }
        ]
      }
    },
    {
      "id": "root_comb_phaser_field",
      "family": "root_comb",
      "title": "COMB/PHASER FIELD",
      "intent": "Rows act as a field of cuts, not a stack of peaks.",
      "bias": "Use when the plot needs staged canyons and coherent center motion.",
      "move": "staged cut field / allpass-like rows",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 450.0,
        "tiltDb": 2.0,
        "canyonDepth": 28.0,
        "qCrank": 0.66,
        "morphSpread": 0.74,
        "density": 0.86
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_comb_phaser_field",
        "family": "root_comb",
        "title": "COMB/PHASER FIELD",
        "intent": "Rows act as a field of cuts, not a stack of peaks.",
        "bias": "Use when the plot needs staged canyons and coherent center motion.",
        "move": "staged cut field / allpass-like rows",
        "anchor_hz": 450.0,
        "anchor_gain_db": 2.8,
        "tilt_db": 2.0,
        "canyon_depth": 28.0,
        "q_crank": 0.66,
        "morph_spread": 0.74,
        "density": 0.86,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 450.0,
            "gain_db": 1.8,
            "bw_oct": 1.8,
            "zero_offset_oct": -0.1,
            "morph_oct": 0.18,
            "zero_morph_oct": -0.18,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.5
          },
          {
            "role": "notch_1",
            "fc_hz": 780.0,
            "gain_db": -7.0,
            "bw_oct": 0.52,
            "zero_offset_oct": 0.18,
            "morph_oct": 0.35,
            "zero_morph_oct": -0.32,
            "zero_secondary_oct": 0.12,
            "q_weight": 0.88
          },
          {
            "role": "notch_2",
            "fc_hz": 1200.0,
            "gain_db": -6.5,
            "bw_oct": 0.5,
            "zero_offset_oct": -0.2,
            "morph_oct": -0.28,
            "zero_morph_oct": 0.34,
            "zero_secondary_oct": -0.1,
            "q_weight": 0.84
          },
          {
            "role": "notch_3",
            "fc_hz": 2180.0,
            "gain_db": -7.8,
            "bw_oct": 0.46,
            "zero_offset_oct": 0.16,
            "morph_oct": 0.46,
            "zero_morph_oct": -0.55,
            "zero_secondary_oct": 0.18,
            "q_weight": 0.92
          },
          {
            "role": "blade",
            "fc_hz": 4440.0,
            "gain_db": -8.4,
            "bw_oct": 0.44,
            "zero_offset_oct": -0.22,
            "morph_oct": -0.42,
            "zero_morph_oct": 0.68,
            "zero_secondary_oct": -0.16,
            "q_weight": 0.86
          },
          {
            "role": "air_notch",
            "fc_hz": 8250.0,
            "gain_db": -5.5,
            "bw_oct": 0.62,
            "zero_offset_oct": 0.28,
            "morph_oct": -0.58,
            "zero_morph_oct": -0.35,
            "zero_secondary_oct": 0.2,
            "q_weight": 0.62
          }
        ]
      },
      "roles": [
        "anchor",
        "notch_1",
        "notch_2",
        "notch_3",
        "blade",
        "air_notch"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 450.0,
            "poleR": 0.9529997,
            "zeroHz": 419.8648,
            "zeroR": 0.5511111,
            "gain": 0.0352908
          },
          {
            "role": "notch_1",
            "poleHz": 780.0,
            "poleR": 0.4955556,
            "zeroHz": 883.6494,
            "zeroR": 0.9266667,
            "gain": 3.75
          },
          {
            "role": "notch_2",
            "poleHz": 1200.0,
            "poleR": 0.4955556,
            "zeroHz": 1044.6607,
            "zeroR": 0.9266667,
            "gain": 3.75
          },
          {
            "role": "notch_3",
            "poleHz": 2180.0,
            "poleR": 0.4955556,
            "zeroHz": 2435.686,
            "zeroR": 0.9266667,
            "gain": 2.1589088
          },
          {
            "role": "blade",
            "poleHz": 4440.0,
            "poleR": 0.4955556,
            "zeroHz": 3812.0305,
            "zeroR": 0.9266667,
            "gain": 1.4479929
          },
          {
            "role": "air_notch",
            "poleHz": 8250.0,
            "poleR": 0.4955556,
            "zeroHz": 10017.1078,
            "zeroR": 0.9266667,
            "gain": 0.5204333
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 493.5256,
            "poleR": 0.9529997,
            "zeroHz": 382.8356,
            "zeroR": 0.5511111,
            "gain": 0.040333
          },
          {
            "role": "notch_1",
            "poleHz": 933.3862,
            "poleR": 0.4955556,
            "zeroHz": 749.8875,
            "zeroR": 0.9266667,
            "gain": 3.75
          },
          {
            "role": "notch_2",
            "poleHz": 1039.4601,
            "poleR": 0.4955556,
            "zeroHz": 1243.6964,
            "zeroR": 0.9266667,
            "gain": 3.75
          },
          {
            "role": "notch_3",
            "poleHz": 2760.1145,
            "poleR": 0.4955556,
            "zeroHz": 1836.9701,
            "zeroR": 0.9266667,
            "gain": 3.75
          },
          {
            "role": "blade",
            "poleHz": 3579.504,
            "poleR": 0.4955556,
            "zeroHz": 5402.9962,
            "zeroR": 0.9266667,
            "gain": 0.6254626
          },
          {
            "role": "air_notch",
            "poleHz": 6127.0563,
            "poleR": 0.4955556,
            "zeroHz": 8370.966,
            "zeroR": 0.9266667,
            "gain": 0.4826141
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 450.0,
            "poleR": 0.9999,
            "zeroHz": 419.8648,
            "zeroR": 0.5709111,
            "gain": 0.0280441
          },
          {
            "role": "notch_1",
            "poleHz": 780.0,
            "poleR": 0.5536356,
            "zeroHz": 960.2926,
            "zeroR": 0.9382827,
            "gain": 3.75
          },
          {
            "role": "notch_2",
            "poleHz": 1200.0,
            "poleR": 0.5509956,
            "zeroHz": 974.7029,
            "zeroR": 0.9377547,
            "gain": 3.75
          },
          {
            "role": "notch_3",
            "poleHz": 2180.0,
            "poleR": 0.5562756,
            "zeroHz": 2759.3494,
            "zeroR": 0.9388107,
            "gain": 1.4250769
          },
          {
            "role": "blade",
            "poleHz": 4440.0,
            "poleR": 0.5523156,
            "zeroHz": 3411.8629,
            "zeroR": 0.9380187,
            "gain": 1.6838496
          },
          {
            "role": "air_notch",
            "poleHz": 8250.0,
            "poleR": 0.5364756,
            "zeroHz": 11506.6352,
            "zeroR": 0.9348507,
            "gain": 0.4303375
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 493.5256,
            "poleR": 0.9999,
            "zeroHz": 382.8356,
            "zeroR": 0.5709111,
            "gain": 0.0338079
          },
          {
            "role": "notch_1",
            "poleHz": 933.3862,
            "poleR": 0.5536356,
            "zeroHz": 814.9289,
            "zeroR": 0.9382827,
            "gain": 3.75
          },
          {
            "role": "notch_2",
            "poleHz": 1039.4601,
            "poleR": 0.5509956,
            "zeroHz": 1160.4098,
            "zeroR": 0.9377547,
            "gain": 3.75
          },
          {
            "role": "notch_3",
            "poleHz": 2760.1145,
            "poleR": 0.5562756,
            "zeroHz": 2081.0738,
            "zeroR": 0.9388107,
            "gain": 2.822769
          },
          {
            "role": "blade",
            "poleHz": 3579.504,
            "poleR": 0.5523156,
            "zeroHz": 4835.8171,
            "zeroR": 0.9380187,
            "gain": 0.696652
          },
          {
            "role": "air_notch",
            "poleHz": 6127.0563,
            "poleR": 0.5364756,
            "zeroHz": 9615.7149,
            "zeroR": 0.9348507,
            "gain": 0.3800654
          }
        ]
      }
    },
    {
      "id": "root_high_bank_collapse",
      "family": "root_collapse",
      "title": "HIGH BANK COLLAPSE",
      "intent": "High rows collapse down into mouth/bite while high zeros cut the top.",
      "bias": "This is the opposite of merely opening the high band upward.",
      "move": "falling air bank into mouth/bite",
      "source": "dev/tmp/measured_foundations + aggregate row-motion rails",
      "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
      "controls": {
        "anchorHz": 390.0,
        "tiltDb": -8.0,
        "canyonDepth": 15.0,
        "qCrank": 0.48,
        "morphSpread": 0.88,
        "density": 0.8
      },
      "metrics": {
        "morphDb": null,
        "qDb": null,
        "tiltDb": null
      },
      "law": {
        "format": "section-law-v1",
        "name": "root_high_bank_collapse",
        "family": "root_collapse",
        "title": "HIGH BANK COLLAPSE",
        "intent": "High rows collapse down into mouth/bite while high zeros cut the top.",
        "bias": "This is the opposite of merely opening the high band upward.",
        "move": "falling air bank into mouth/bite",
        "anchor_hz": 390.0,
        "anchor_gain_db": 4.2,
        "tilt_db": -8.0,
        "canyon_depth": 15.0,
        "q_crank": 0.48,
        "morph_spread": 0.88,
        "density": 0.8,
        "source_contract": null,
        "sections": [
          {
            "role": "anchor",
            "fc_hz": 390.0,
            "gain_db": 2.8,
            "bw_oct": 2.5,
            "zero_offset_oct": -1.0,
            "morph_oct": 0.08,
            "zero_morph_oct": 0.25,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.5
          },
          {
            "role": "low_keep",
            "fc_hz": 545.0,
            "gain_db": 1.4,
            "bw_oct": 1.8,
            "zero_offset_oct": -0.35,
            "morph_oct": 0.28,
            "zero_morph_oct": 0.15,
            "zero_secondary_oct": -0.1,
            "q_weight": 0.48
          },
          {
            "role": "mouth_landing",
            "fc_hz": 780.0,
            "gain_db": 3.8,
            "bw_oct": 0.92,
            "zero_offset_oct": 0.22,
            "morph_oct": 0.55,
            "zero_morph_oct": -0.2,
            "zero_secondary_oct": 0.0,
            "q_weight": 0.82
          },
          {
            "role": "bite_landing",
            "fc_hz": 2220.0,
            "gain_db": 3.0,
            "bw_oct": 0.76,
            "zero_offset_oct": -0.18,
            "morph_oct": -0.35,
            "zero_morph_oct": 0.32,
            "zero_secondary_oct": 0.12,
            "q_weight": 0.9
          },
          {
            "role": "falling_tear",
            "fc_hz": 9650.0,
            "gain_db": -5.4,
            "bw_oct": 0.92,
            "zero_offset_oct": 0.18,
            "morph_oct": -0.8,
            "zero_morph_oct": -0.05,
            "zero_secondary_oct": 0.1,
            "q_weight": 0.56
          },
          {
            "role": "air_kill",
            "fc_hz": 18000.0,
            "gain_db": -6.4,
            "bw_oct": 1.2,
            "zero_offset_oct": 0.05,
            "morph_oct": -0.25,
            "zero_morph_oct": 0.0,
            "zero_secondary_oct": 0.05,
            "q_weight": 0.35
          }
        ]
      },
      "roles": [
        "anchor",
        "low_keep",
        "mouth_landing",
        "bite_landing",
        "falling_tear",
        "air_kill"
      ],
      "corners": {
        "M0_Q0": [
          {
            "role": "anchor",
            "poleHz": 390.0,
            "poleR": 0.9404349,
            "zeroHz": 195.0,
            "zeroR": 0.4716667,
            "gain": 0.0259213
          },
          {
            "role": "low_keep",
            "poleHz": 545.0,
            "poleR": 0.9433634,
            "zeroHz": 427.5983,
            "zeroR": 0.4716667,
            "gain": 0.0371495
          },
          {
            "role": "mouth_landing",
            "poleHz": 780.0,
            "poleR": 0.9601318,
            "zeroHz": 908.4922,
            "zeroR": 0.4716667,
            "gain": 0.0576886
          },
          {
            "role": "bite_landing",
            "poleHz": 2220.0,
            "poleR": 0.9092399,
            "zeroHz": 1959.6007,
            "zeroR": 0.4716667,
            "gain": 0.3775932
          },
          {
            "role": "falling_tear",
            "poleHz": 9650.0,
            "poleR": 0.5858333,
            "zeroHz": 10932.3295,
            "zeroR": 0.84,
            "gain": 0.6544788
          },
          {
            "role": "air_kill",
            "poleHz": 18000.0,
            "poleR": 0.5858333,
            "zeroHz": 18634.7686,
            "zeroR": 0.84,
            "gain": 0.73616
          }
        ],
        "M100_Q0": [
          {
            "role": "anchor",
            "poleHz": 409.503,
            "poleR": 0.9404349,
            "zeroHz": 227.123,
            "zeroR": 0.4716667,
            "gain": 0.0272612
          },
          {
            "role": "low_keep",
            "poleHz": 646.5026,
            "poleR": 0.9433634,
            "zeroHz": 468.5673,
            "zeroR": 0.4716667,
            "gain": 0.0475487
          },
          {
            "role": "mouth_landing",
            "poleHz": 1090.9205,
            "poleR": 0.9601318,
            "zeroHz": 804.1553,
            "zeroR": 0.4716667,
            "gain": 0.1082769
          },
          {
            "role": "bite_landing",
            "poleHz": 1793.2289,
            "poleR": 0.9092399,
            "zeroHz": 2381.9773,
            "zeroR": 0.4716667,
            "gain": 0.2398656
          },
          {
            "role": "falling_tear",
            "poleHz": 5923.8247,
            "poleR": 0.5858333,
            "zeroHz": 10603.9432,
            "zeroR": 0.84,
            "gain": 0.3439776
          },
          {
            "role": "air_kill",
            "poleHz": 15454.1779,
            "poleR": 0.5858333,
            "zeroHz": 18634.7686,
            "zeroR": 0.84,
            "gain": 0.6744982
          }
        ],
        "M0_Q100": [
          {
            "role": "anchor",
            "poleHz": 390.0,
            "poleR": 0.9999,
            "zeroHz": 195.0,
            "zeroR": 0.4860667,
            "gain": 0.025
          },
          {
            "role": "low_keep",
            "poleHz": 545.0,
            "poleR": 0.9563894,
            "zeroHz": 398.9634,
            "zeroR": 0.4854907,
            "gain": 0.0346689
          },
          {
            "role": "mouth_landing",
            "poleHz": 780.0,
            "poleR": 0.9757845,
            "zeroHz": 908.4922,
            "zeroR": 0.4952827,
            "gain": 0.0600306
          },
          {
            "role": "bite_landing",
            "poleHz": 2220.0,
            "poleR": 0.9484051,
            "zeroHz": 2129.5663,
            "zeroR": 0.4975867,
            "gain": 0.3942635
          },
          {
            "role": "falling_tear",
            "poleHz": 9650.0,
            "poleR": 0.6127133,
            "zeroHz": 11716.9806,
            "zeroR": 0.845376,
            "gain": 0.6047498
          },
          {
            "role": "air_kill",
            "poleHz": 18000.0,
            "poleR": 0.6026333,
            "zeroHz": 18750.0,
            "zeroR": 0.84336,
            "gain": 0.7480952
          }
        ],
        "M100_Q100": [
          {
            "role": "anchor",
            "poleHz": 409.503,
            "poleR": 0.9999,
            "zeroHz": 227.123,
            "zeroR": 0.4860667,
            "gain": 0.025
          },
          {
            "role": "low_keep",
            "poleHz": 646.5026,
            "poleR": 0.9563894,
            "zeroHz": 437.1887,
            "zeroR": 0.4854907,
            "gain": 0.0458028
          },
          {
            "role": "mouth_landing",
            "poleHz": 1090.9205,
            "poleR": 0.9757845,
            "zeroHz": 804.1553,
            "zeroR": 0.4952827,
            "gain": 0.1161719
          },
          {
            "role": "bite_landing",
            "poleHz": 1793.2289,
            "poleR": 0.9484051,
            "zeroHz": 2588.5778,
            "zeroR": 0.4975867,
            "gain": 0.2401036
          },
          {
            "role": "falling_tear",
            "poleHz": 5923.8247,
            "poleR": 0.6127133,
            "zeroHz": 11365.0249,
            "zeroR": 0.845376,
            "gain": 0.3102535
          },
          {
            "role": "air_kill",
            "poleHz": 15454.1779,
            "poleR": 0.6026333,
            "zeroHz": 18750.0,
            "zeroR": 0.84336,
            "gain": 0.6849746
          }
        ]
      }
    }
  ]
};
export const FAMILY_LAWS = FAMILY_AUTHORING.families;
