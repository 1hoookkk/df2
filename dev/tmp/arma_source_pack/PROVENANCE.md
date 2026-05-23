# ARMA Source Pack Provenance

Created: 2026-05-23

Purpose: destructive ARMA / Prony / Steiglitz-McBride fitting experiments for df2 authoring. These are source-audio references only, not shipped cartridge coefficients.

## WAV folder

`wav/` contains fitter-friendly WAV files. AU, MP3, and OGG sources were converted with ffmpeg to mono 48 kHz PCM WAV. Native OpenAIR WAVs were copied as downloaded.

## Raw folder

`raw/` contains the original downloaded files.

## Sources

- `inspire_3tweeks.au` -> `wav/inspire_3tweeks.wav`
  - Source: The INSPIRE Project audio archive
  - URL: https://theinspireproject.org/downloads/AUDIO%20FILES/3tweeks.au
  - Use: tweek / VLF hook source
- `inspire_52hopwhist.au` -> `wav/inspire_52hopwhist.wav`
  - Source: The INSPIRE Project audio archive
  - URL: https://theinspireproject.org/downloads/AUDIO%20FILES/52hopwhist.au
  - Use: whistler source
- `inspire_7purewhist.au` -> `wav/inspire_7purewhist.wav`
  - Source: The INSPIRE Project audio archive
  - URL: https://theinspireproject.org/downloads/AUDIO%20FILES/7purewhist.au
  - Use: clean whistler source
- `inspire_chorus.au` -> `wav/inspire_chorus.wav`
  - Source: The INSPIRE Project audio archive
  - URL: https://theinspireproject.org/downloads/AUDIO%20FILES/chorus.au
  - Use: chorus / bubbling VLF source
- `openair_hamilton_mausoleum_hm2_000_wx_48k.wav`
  - Source: OpenAIR, Audiolab, University of York / Damian T. Murphy
  - URL: https://webfiles.york.ac.uk/OPENAIR/IRs/hamilton-mausoleum/examples/hm2_000_wx_48k.wav
  - Page: https://openairlib.net/?page_id=502
  - License noted by OpenAIR page: CC BY 4.0
  - Use: long architectural impulse response
- `openair_r1_nuclear_reactor_hall_r1_omni_48k.wav`
  - Source: OpenAIR, Audiolab, University of York / KTH Royal Institute of Technology
  - URL: https://webfiles.york.ac.uk/OPENAIR/IRs/r1-nuclear-reactor-hall/examples/r1_omni_48k.wav
  - Page: https://www.openair.hosted.york.ac.uk/?page_id=626
  - License noted by OpenAIR page: CC BY 4.0
  - Use: hard/industrial hall impulse response
- `openair_innocent_railway_tunnel_entrance.wav`
  - Source: OpenAIR, University of York
  - URL: https://webfiles.york.ac.uk/OPENAIR/IRs/innocent-railway-tunnel/examples/tunnel_entrance_f_1way_mono_processed.wav
  - Use: tunnel / comb-like impulse response
- `conet_swedish_rhapsody.mp3` -> `wav/conet_swedish_rhapsody.wav`
  - Source: The Conet Project, Internet Archive item `ird059`
  - URL: https://archive.org/download/ird059/tcp_d1_01_the_swedish_rhapsody_irdial.mp3
  - Use: shortwave fading / numbers-station carrier/noise bed
- `conet_5_dashes.mp3` -> `wav/conet_5_dashes.wav`
  - Source: The Conet Project, Internet Archive item `ird059`
  - URL: https://archive.org/download/ird059/tcp_d1_05_5_dashes_irdial.mp3
  - Use: shortwave fading / tone-plus-noise station material
- `wikimedia_carotid_doppler.ogg` -> `wav/wikimedia_carotid_doppler.wav`
  - Source: Wikimedia Commons, `File:Carotid.ogg`
  - URL: https://commons.wikimedia.org/wiki/Special:Redirect/file/Carotid.ogg
  - Page: https://commons.wikimedia.org/wiki/File:Carotid.ogg
  - License noted by Commons page: public domain
  - Use: vascular Doppler turbulence source
- `raw/stolaf_nmrtalk/*_fid.bin` + `raw/stolaf_nmrtalk/*_acqus.txt` -> `wav/stolaf_nmrtalk/*_real_48k.wav`
  - Source: NMR-Talk, Bob Hanson, St. Olaf College
  - Page: https://www.stolaf.edu/people/hansonr/nmrtalk/
  - Samples: cyclohexane, dichloromethane, cyclohexane/dichloromethane mixture, ethyl acetate, inositol
  - Original data: Bruker FID binary (`fid.bin`) with acquisition metadata (`acqus.txt`)
  - Conversion: interpreted `DTYPA=0`, `BYTORDA=1` 32-bit integer FID data; used the interleaved real component; normalized to mono WAV at native `SW_h`, then resampled to 48 kHz for the main WAV folder
  - Use: decaying NMR free-induction resonance source

## Notes

- University of Twente WebSDR is live-recording oriented, so it was not included in this static download bundle.
- Clinical Doppler datasets can be much larger or credentialed; this pack uses a public-domain carotid Doppler clip as the lightweight medical seed.
- NMR-Talk files are not ordinary audio recordings; the WAVs are audible renders of FID data for fitting experiments. Keep the raw `fid.bin` and `acqus.txt` together for provenance.
- Before mapping fitted coefficients into df2, run root checks and reflect/clamp unstable poles inside the unit circle. Do not change cascade topology or cartridge format.
