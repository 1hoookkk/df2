# P2K Frequency Rails (measured Hz)

Where poles and zeros actually LAND across 50 P2K skins / 200 variant bodies,
measured through the shipped engine (`trench_core.dll`) over a 5x5 Morph x
Secondary grid. Clean-room: landing FREQUENCIES only, no coefficients.
`bodies` = how many of the 50 skins use the rail. `hits` = uses at a body
corner (HOME / AWAY / PUSH HOME / PUSH AWAY).

No vibe-bands. A rail means something ONLY when it sits on a real measured
frequency (a vowel formant, a tube partial, a metal mode) within a quartertone.
Everything else is just a frequency the engine returns to.

## Rails that land on known physics (within 50 cents)

Category = the physical model that makes the resonance. For tubes, open vs
closed is a SUBcategory (not its own category).

### vowel formant

| Hz | pole/zero | lands on | bodies | hits |
|---:|---|---|---:|---:|
| 265 | pole | iy:f1 = 270.0 Hz (+32c) | 34 | 10 |
| 270 | pole | iy:f1 = 270.0 Hz (+0c) | 36 | 9 |
| 270 | zero | iy:f1 = 270.0 Hz (+0c) | 22 | 8 |
| 275 | pole | iy:f1 = 270.0 Hz (+32c) | 35 | 10 |
| 340 | pole | u:f1 = 342.0 Hz (+10c) | 26 | 7 |
| 355 | pole | u:f1 = 350.0 Hz (+25c) | 39 | 9 |
| 355 | zero | u:f1 = 350.0 Hz (+25c) | 25 | 9 |
| 360 | zero | u:f1 = 350.0 Hz (+49c) | 28 | 14 |
| 360 | pole | u:f1 = 350.0 Hz (+49c) | 35 | 8 |
| 390 | pole | ih:f1 = 390.0 Hz (+0c) | 40 | 9 |
| 400 | pole | ih:f1 = 390.0 Hz (+44c) | 32 | 13 |
| 430 | pole | uu:f1 = 440.0 Hz (+40c) | 29 | 25 |
| 430 | zero | uu:f1 = 440.0 Hz (+40c) | 25 | 15 |
| 440 | pole | uu:f1 = 440.0 Hz (+0c) | 36 | 15 |
| 445 | zero | uu:f1 = 440.0 Hz (+20c) | 24 | 8 |
| 450 | pole | uu:f1 = 440.0 Hz (+39c) | 31 | 28 |
| 450 | zero | uu:f1 = 440.0 Hz (+39c) | 21 | 22 |
| 490 | pole | er:f1 = 490.0 Hz (+0c) | 31 | 11 |
| 490 | zero | er:f1 = 490.0 Hz (+0c) | 24 | 10 |
| 495 | pole | er:f1 = 490.0 Hz (+18c) | 29 | 9 |
| 525 | pole | eh:f1 = 530.0 Hz (+16c) | 40 | 8 |
| 530 | pole | eh:f1 = 530.0 Hz (+0c) | 41 | 10 |
| 530 | zero | eh:f1 = 530.0 Hz (+0c) | 29 | 8 |
| 535 | pole | o:f1 = 540.0 Hz (+16c) | 30 | 12 |
| 540 | pole | o:f1 = 540.0 Hz (+0c) | 31 | 12 |
| 545 | zero | e:f1 = 542.0 Hz (+10c) | 34 | 30 |
| 545 | pole | e:f1 = 542.0 Hz (+10c) | 34 | 16 |
| 550 | pole | e:f1 = 542.0 Hz (+25c) | 30 | 10 |
| 565 | zero | ao:f1 = 570.0 Hz (+15c) | 18 | 11 |
| 570 | zero | ao:f1 = 570.0 Hz (+0c) | 25 | 8 |
| 575 | zero | ao:f1 = 570.0 Hz (+15c) | 14 | 7 |
| 580 | pole | ao:f1 = 570.0 Hz (+30c) | 19 | 8 |
| 605 | pole | o:f1 = 615.0 Hz (+28c) | 29 | 13 |
| 605 | zero | o:f1 = 615.0 Hz (+28c) | 19 | 10 |
| 620 | pole | o:f1 = 615.0 Hz (+14c) | 28 | 13 |
| 635 | pole | uh:f1 = 640.0 Hz (+14c) | 23 | 10 |
| 640 | zero | uh:f1 = 640.0 Hz (+0c) | 27 | 10 |
| 640 | pole | uh:f1 = 640.0 Hz (+0c) | 32 | 8 |
| 650 | zero | ae:f1 = 660.0 Hz (+26c) | 21 | 7 |
| 695 | pole | a:f1 = 700.0 Hz (+12c) | 29 | 7 |
| 700 | zero | a:f1 = 700.0 Hz (+0c) | 18 | 7 |
| 710 | zero | a:f1 = 700.0 Hz (+25c) | 29 | 14 |
| 715 | pole | aa:f1 = 730.0 Hz (+36c) | 21 | 7 |
| 720 | zero | aa:f1 = 730.0 Hz (+24c) | 17 | 11 |
| 720 | pole | aa:f1 = 730.0 Hz (+24c) | 25 | 8 |
| 820 | pole | ao:f2 = 840.0 Hz (+42c) | 20 | 12 |
| 830 | pole | ao:f2 = 840.0 Hz (+21c) | 26 | 11 |
| 840 | pole | ao:f2 = 840.0 Hz (+0c) | 20 | 8 |
| 870 | pole | uw:f2 = 870.0 Hz (+0c) | 19 | 10 |
| 890 | pole | uw:f2 = 870.0 Hz (+39c) | 24 | 7 |
| 890 | zero | uw:f2 = 870.0 Hz (+39c) | 21 | 7 |
| 1000 | pole | o:f2 = 990.0 Hz (+17c) | 25 | 12 |
| 1010 | pole | uu:f2 = 1020.0 Hz (+17c) | 32 | 9 |
| 1020 | pole | uu:f2 = 1020.0 Hz (+0c) | 36 | 12 |
| 1050 | pole | u:f2 = 1067.0 Hz (+28c) | 39 | 9 |
| 1060 | pole | u:f2 = 1067.0 Hz (+11c) | 33 | 12 |
| 1060 | zero | u:f2 = 1067.0 Hz (+11c) | 23 | 11 |
| 1070 | pole | u:f2 = 1067.0 Hz (+5c) | 29 | 7 |
| 1080 | pole | aa:f2 = 1090.0 Hz (+16c) | 29 | 10 |
| 1090 | zero | aa:f2 = 1090.0 Hz (+0c) | 24 | 17 |
| 1090 | pole | aa:f2 = 1090.0 Hz (+0c) | 29 | 8 |
| 1100 | pole | o:f2 = 1100.0 Hz (+0c) | 31 | 10 |
| 1110 | pole | o:f2 = 1100.0 Hz (+16c) | 21 | 8 |
| 1170 | pole | uh:f2 = 1190.0 Hz (+29c) | 33 | 11 |
| 1190 | zero | uh:f2 = 1190.0 Hz (+0c) | 26 | 13 |
| 1240 | zero | u:f2 = 1250.0 Hz (+14c) | 17 | 8 |
| 1250 | pole | u:f2 = 1250.0 Hz (+0c) | 28 | 7 |
| 1250 | zero | u:f2 = 1250.0 Hz (+0c) | 16 | 7 |
| 1280 | zero | u:f2 = 1250.0 Hz (+41c) | 20 | 13 |
| 1280 | pole | u:f2 = 1250.0 Hz (+41c) | 28 | 8 |
| 1330 | pole | er:f2 = 1350.0 Hz (+26c) | 24 | 7 |
| 1350 | pole | er:f2 = 1350.0 Hz (+0c) | 25 | 8 |
| 1360 | zero | er:f2 = 1350.0 Hz (+13c) | 19 | 9 |
| 1650 | zero | er:f3 = 1690.0 Hz (+41c) | 15 | 10 |
| 1660 | pole | er:f3 = 1690.0 Hz (+31c) | 22 | 12 |
| 1740 | zero | ae:f2 = 1720.0 Hz (+20c) | 21 | 8 |
| 1790 | pole | eh:f2 = 1840.0 Hz (+48c) | 26 | 11 |
| 1820 | zero | eh:f2 = 1840.0 Hz (+19c) | 21 | 14 |
| 1840 | zero | eh:f2 = 1840.0 Hz (+0c) | 20 | 10 |
| 1850 | zero | eh:f2 = 1840.0 Hz (+9c) | 18 | 13 |
| 1950 | zero | ih:f2 = 1990.0 Hz (+35c) | 21 | 7 |
| 1970 | pole | ih:f2 = 1990.0 Hz (+17c) | 23 | 8 |
| 1980 | pole | ih:f2 = 1990.0 Hz (+9c) | 24 | 7 |
| 2000 | zero | ih:f2 = 1990.0 Hz (+9c) | 18 | 12 |
| 2010 | zero | ih:f2 = 1990.0 Hz (+17c) | 22 | 15 |
| 2020 | pole | ih:f2 = 1990.0 Hz (+26c) | 22 | 7 |
| 2150 | pole | u:f3 = 2200.0 Hz (+40c) | 23 | 10 |
| 2160 | pole | u:f3 = 2200.0 Hz (+32c) | 27 | 8 |
| 2170 | pole | u:f3 = 2200.0 Hz (+24c) | 22 | 9 |
| 2180 | zero | u:f3 = 2200.0 Hz (+16c) | 24 | 19 |
| 2210 | pole | u:f3 = 2219.0 Hz (+7c) | 21 | 7 |
| 2220 | zero | u:f3 = 2219.0 Hz (+1c) | 12 | 40 |
| 2220 | pole | u:f3 = 2219.0 Hz (+1c) | 22 | 7 |
| 2230 | pole | uw:f3 = 2240.0 Hz (+8c) | 25 | 9 |
| 2280 | pole | iy:f2 = 2290.0 Hz (+8c) | 20 | 7 |
| 2320 | zero | o:f3 = 2300.0 Hz (+15c) | 17 | 12 |
| 2340 | pole | o:f3 = 2300.0 Hz (+30c) | 16 | 10 |
| 2430 | zero | aa:f3 = 2440.0 Hz (+7c) | 12 | 7 |
| 2550 | zero | ih:f3 = 2550.0 Hz (+0c) | 19 | 8 |
| 2600 | zero | a:f3 = 2600.0 Hz (+0c) | 14 | 7 |
| 2610 | pole | a:f3 = 2600.0 Hz (+7c) | 23 | 9 |
| 2650 | zero | a:f3 = 2600.0 Hz (+33c) | 17 | 11 |
| 2650 | pole | a:f3 = 2600.0 Hz (+33c) | 23 | 8 |
| 2940 | zero | iy:f3 = 3010.0 Hz (+41c) | 18 | 7 |
| 2960 | pole | iy:f3 = 3010.0 Hz (+29c) | 29 | 8 |
| 2970 | zero | iy:f3 = 3010.0 Hz (+23c) | 20 | 12 |
| 3000 | pole | iy:f3 = 3010.0 Hz (+6c) | 18 | 7 |
| 3310 | zero | a:f4 = 3300.0 Hz (+5c) | 12 | 10 |
| 3470 | zero | a:f4 = 3464.0 Hz (+3c) | 13 | 7 |
| 3490 | pole | e:f4 = 3511.0 Hz (+10c) | 17 | 7 |
| 3500 | zero | e:f4 = 3511.0 Hz (+5c) | 16 | 10 |
| 3610 | pole | e:f4 = 3511.0 Hz (+48c) | 13 | 7 |

### tube

**closed-open**

| Hz | pole/zero | lands on | bodies | hits |
|---:|---|---|---:|---:|
| 172 | pole | co_50cm:p1 = 172.0 Hz (+0c) | 25 | 7 |
| 465 | zero | co_18cm:p1 = 476.0 Hz (+40c) | 23 | 9 |
| 470 | pole | co_18cm:p1 = 476.0 Hz (+22c) | 33 | 10 |
| 480 | pole | co_18cm:p1 = 476.0 Hz (+14c) | 34 | 8 |
| 505 | pole | co_50cm:p2 = 515.0 Hz (+34c) | 32 | 9 |
| 510 | pole | co_50cm:p2 = 515.0 Hz (+17c) | 37 | 8 |
| 515 | zero | co_50cm:p2 = 515.0 Hz (+0c) | 23 | 11 |
| 520 | pole | co_50cm:p2 = 515.0 Hz (+17c) | 31 | 12 |
| 520 | zero | co_50cm:p2 = 515.0 Hz (+17c) | 22 | 11 |
| 850 | pole | co_50cm:p3 = 858.0 Hz (+16c) | 22 | 10 |
| 1420 | zero | co_18cm:p2 = 1429.0 Hz (+11c) | 29 | 15 |
| 1430 | pole | co_18cm:p2 = 1429.0 Hz (+1c) | 31 | 10 |
| 1440 | pole | co_18cm:p2 = 1429.0 Hz (+13c) | 31 | 13 |
| 1440 | zero | co_18cm:p2 = 1429.0 Hz (+13c) | 24 | 9 |
| 1470 | zero | co_18cm:p2 = 1429.0 Hz (+49c) | 27 | 10 |
| 1580 | zero | co_50cm:p5 = 1544.0 Hz (+40c) | 11 | 7 |
| 1880 | pole | co_50cm:p6 = 1887.0 Hz (+6c) | 18 | 7 |
| 1890 | pole | co_50cm:p6 = 1887.0 Hz (+3c) | 29 | 10 |
| 2360 | pole | co_18cm:p3 = 2381.0 Hz (+15c) | 19 | 7 |
| 2370 | zero | co_18cm:p3 = 2381.0 Hz (+8c) | 12 | 10 |
| 2370 | pole | co_18cm:p3 = 2381.0 Hz (+8c) | 20 | 7 |
| 2380 | zero | co_18cm:p3 = 2381.0 Hz (+1c) | 18 | 13 |
| 2380 | pole | co_18cm:p3 = 2381.0 Hz (+1c) | 20 | 8 |
| 3080 | zero | co_25cm:p5 = 3087.0 Hz (+4c) | 19 | 10 |
| 3100 | zero | co_25cm:p5 = 3087.0 Hz (+7c) | 20 | 12 |
| 3150 | zero | co_25cm:p5 = 3087.0 Hz (+35c) | 15 | 7 |
| 3320 | pole | co_18cm:p4 = 3334.0 Hz (+7c) | 17 | 11 |


**open-open**

| Hz | pole/zero | lands on | bodies | hits |
|---:|---|---|---:|---:|
| 345 | pole | oo_50cm:p1 = 343.0 Hz (+10c) | 33 | 14 |
| 680 | zero | oo_50cm:p2 = 686.0 Hz (+15c) | 19 | 16 |
| 680 | pole | oo_50cm:p2 = 686.0 Hz (+15c) | 30 | 13 |
| 950 | zero | oo_18cm:p1 = 953.0 Hz (+5c) | 18 | 7 |
| 955 | zero | oo_18cm:p1 = 953.0 Hz (+4c) | 22 | 9 |
| 1040 | pole | oo_50cm:p3 = 1029.0 Hz (+18c) | 37 | 13 |
| 1390 | pole | oo_50cm:p4 = 1372.0 Hz (+23c) | 28 | 8 |
| 1400 | zero | oo_50cm:p4 = 1372.0 Hz (+35c) | 30 | 14 |
| 1900 | zero | oo_18cm:p2 = 1906.0 Hz (+5c) | 17 | 9 |
| 1910 | zero | oo_18cm:p2 = 1906.0 Hz (+4c) | 15 | 11 |
| 1930 | zero | oo_18cm:p2 = 1906.0 Hz (+22c) | 19 | 10 |
| 2030 | pole | oo_50cm:p6 = 2058.0 Hz (+24c) | 27 | 14 |
| 2090 | pole | oo_50cm:p6 = 2058.0 Hz (+27c) | 21 | 7 |
| 2720 | zero | oo_25cm:p4 = 2744.0 Hz (+15c) | 20 | 7 |
| 2730 | zero | oo_25cm:p4 = 2744.0 Hz (+9c) | 16 | 8 |
| 2760 | zero | oo_25cm:p4 = 2744.0 Hz (+10c) | 23 | 9 |
| 2810 | zero | oo_18cm:p3 = 2858.0 Hz (+29c) | 19 | 9 |
| 2840 | zero | oo_18cm:p3 = 2858.0 Hz (+11c) | 25 | 16 |
| 2840 | pole | oo_18cm:p3 = 2858.0 Hz (+11c) | 23 | 9 |
| 2850 | zero | oo_18cm:p3 = 2858.0 Hz (+5c) | 23 | 9 |
| 2860 | pole | oo_18cm:p3 = 2858.0 Hz (+1c) | 16 | 7 |
| 2880 | pole | oo_18cm:p3 = 2858.0 Hz (+13c) | 23 | 8 |
| 2880 | zero | oo_18cm:p3 = 2858.0 Hz (+13c) | 16 | 7 |
| 2890 | pole | oo_18cm:p3 = 2858.0 Hz (+19c) | 21 | 8 |
| 2890 | zero | oo_18cm:p3 = 2858.0 Hz (+19c) | 12 | 7 |
| 2900 | pole | oo_18cm:p3 = 2858.0 Hz (+25c) | 17 | 10 |
| 3420 | zero | oo_25cm:p5 = 3430.0 Hz (+5c) | 15 | 7 |
| 3430 | zero | oo_25cm:p5 = 3430.0 Hz (+0c) | 13 | 7 |
| 3740 | zero | oo_18cm:p4 = 3811.0 Hz (+33c) | 10 | 8 |
| 3770 | pole | oo_18cm:p4 = 3811.0 Hz (+19c) | 14 | 7 |
| 3770 | zero | oo_18cm:p4 = 3811.0 Hz (+19c) | 14 | 7 |
| 3790 | pole | oo_18cm:p4 = 3811.0 Hz (+10c) | 24 | 43 |
| 3790 | zero | oo_18cm:p4 = 3811.0 Hz (+10c) | 17 | 30 |
| 3830 | zero | oo_18cm:p4 = 3811.0 Hz (+9c) | 15 | 9 |
| 3860 | zero | oo_18cm:p4 = 3811.0 Hz (+22c) | 11 | 8 |
| 3870 | zero | oo_18cm:p4 = 3811.0 Hz (+27c) | 10 | 10 |
| 4010 | zero | oo_25cm:p6 = 4116.0 Hz (+45c) | 11 | 13 |
| 4040 | pole | oo_25cm:p6 = 4116.0 Hz (+32c) | 15 | 8 |
| 4060 | pole | oo_25cm:p6 = 4116.0 Hz (+24c) | 14 | 7 |
| 4130 | zero | oo_25cm:p6 = 4116.0 Hz (+6c) | 28 | 50 |
| 4750 | pole | oo_18cm:p5 = 4764.0 Hz (+5c) | 16 | 7 |
| 5025 | zero | oo_10cm:p3 = 5145.0 Hz (+41c) | 11 | 9 |
| 5100 | zero | oo_10cm:p3 = 5145.0 Hz (+15c) | 20 | 8 |
| 5625 | zero | oo_18cm:p6 = 5717.0 Hz (+28c) | 12 | 9 |
| 5675 | zero | oo_18cm:p6 = 5717.0 Hz (+13c) | 19 | 12 |
| 5725 | pole | oo_18cm:p6 = 5717.0 Hz (+2c) | 15 | 7 |
| 5800 | pole | oo_18cm:p6 = 5717.0 Hz (+25c) | 18 | 7 |
| 5875 | zero | oo_18cm:p6 = 5717.0 Hz (+47c) | 26 | 9 |
| 5875 | pole | oo_18cm:p6 = 5717.0 Hz (+47c) | 21 | 8 |
| 6850 | zero | oo_10cm:p4 = 6860.0 Hz (+3c) | 16 | 8 |
| 7000 | zero | oo_10cm:p4 = 6860.0 Hz (+35c) | 14 | 7 |
| 7050 | zero | oo_10cm:p4 = 6860.0 Hz (+47c) | 21 | 7 |
| 8725 | zero | oo_10cm:p5 = 8575.0 Hz (+30c) | 12 | 11 |
| 8800 | pole | oo_10cm:p5 = 8575.0 Hz (+45c) | 14 | 8 |


## Strongest rails with NO physics match (the engine's own landing spots, by use)

These are real measured frequencies too — they just don't coincide with a vowel,
tube, or metal frequency. Sorted by how load-bearing they are.

| Hz | pole/zero | bodies | hits |
|---:|---|---:|---:|
| 2 | pole | 17 | 330 |
| 2 | zero | 17 | 325 |
| 780 | pole | 31 | 179 |
| 780 | zero | 31 | 175 |
| 785 | zero | 30 | 133 |
| 785 | pole | 27 | 129 |
| 8250 | zero | 28 | 50 |
| 17950 | zero | 26 | 50 |
| 16500 | zero | 27 | 48 |
| 790 | zero | 24 | 43 |
| 9650 | zero | 16 | 43 |
| 134 | zero | 19 | 41 |
| 8875 | zero | 9 | 41 |
| 134 | pole | 28 | 40 |
| 4440 | zero | 12 | 40 |
| 790 | pole | 27 | 28 |
| 365 | pole | 34 | 22 |
| 320 | zero | 33 | 20 |
| 5450 | pole | 20 | 18 |
| 410 | pole | 32 | 17 |
| 200 | pole | 28 | 17 |
| 5450 | zero | 23 | 17 |
| 365 | zero | 20 | 16 |
| 12375 | zero | 16 | 15 |
| 590 | zero | 12 | 14 |
| 13300 | pole | 8 | 14 |
| 460 | zero | 23 | 13 |
| 800 | pole | 15 | 13 |
| 12 | pole | 5 | 13 |
| 1140 | zero | 25 | 12 |
| 1620 | zero | 25 | 12 |
| 6150 | zero | 17 | 12 |
| 925 | zero | 16 | 12 |
| 8025 | zero | 16 | 12 |
| 6600 | zero | 13 | 12 |
| 370 | pole | 40 | 11 |
| 590 | pole | 18 | 11 |
| 180 | zero | 15 | 11 |
| 11350 | zero | 13 | 11 |
| 320 | pole | 36 | 10 |
