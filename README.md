# Folio Reel

A straightforward video editor for Zorin OS and Ubuntu: put clips on a timeline, trim them, add
titles and music, and make a file. Part of Folio Studio.

It is the newest app in the suite and the least finished. What is here works; Backlog 4 lists
what a video editor still needs (waveforms, chroma key, subtitles, proxies, markers).

## What it does

- **Media**: import video, pictures and sound; record the screen, a window, a webcam or the
  microphone straight onto the timeline.
- **Timeline**: several tracks, drag to arrange, trim, split, ripple delete, snapping, zoom.
- **Clips**: speed, volume, fade in and out, pan and zoom (Ken Burns), crop, mute, and colour
  changes — brighter, darker, contrast, black and white — with keyframes.
- **Between clips**: transitions with a duration you choose.
- **Text**: titles, captions and lower thirds.
- **Sound**: a music bed that ducks under speech.
- **Export**: MP4 or WebM, at 24, 25, 30 or 60 frames a second, in 16:9, 4:3, 1:1 or 9:16.

## Layout

| Folder | What's in it |
| --- | --- |
| `app/folio_reel` | the whole app, in Python with GTK 3; `engine.py` drives GStreamer for playback and export |
| `share` | icons and themes |
| `tests` | engine, command-line, interface and theme tests |
| `tools` | the release script |

## Building and testing

```sh
cd app && python3 -m folio_reel         # run it
python3 tests/test_engine.py            # the engine
sh tests/run_ui.sh ui_basic.py          # the interface, on an X display
sh tests/theme_run.sh                   # desktop themes (X2-01)
sh build-deb.sh out/                    # the package
XD=95 tools/release.sh                  # everything, on the three test machines
```

Needs python3-gi, GTK 3 and GStreamer (base, good, bad, libav).
