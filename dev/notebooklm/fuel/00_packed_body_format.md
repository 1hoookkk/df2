# What a body is

A body is **240 bytes of packed words**.

```
240 bytes = 4 corners x 6 rows x 5 packed words
```

- **Packed words** are the format on disk. They decode into Hz.
- Each **row** = one pole (a peak) + one zero (a notch), in Hz.
- **6 rows** stacked = the sound.
- **4 corners** = four saved versions you blend between:
  - HOME = Morph 0, Push 0
  - AWAY = Morph 100, Push 0
  - PUSH HOME = Morph 0, Push 100
  - PUSH AWAY = Morph 100, Push 100

## Two knobs

- **Morph** slides HOME -> AWAY.
- **Push** is a stress move (tighter / harder / hollower).

## Two rules

- **Row i only blends with row i.** Row 3 always meets row 3.
- **Zeros matter as much as poles.** A lot of the character is the notch moving away from the peak.

Words are the truth on disk. Hz is how you read them.
