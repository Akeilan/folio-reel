# Folio Reel

A straightforward video editor for Zorin OS and Ubuntu: put clips on a timeline, trim them, add
titles and music, and make a file. Part of Folio Studio.

It is the newest app in the suite and the least finished. What is here works; Backlog 4 lists
what a video editor still needs (markers, nested clips, stabilisation).

## What it does

- **Media**: import video, pictures and sound; record the screen, a window, a webcam or the
  microphone straight onto the timeline.
- **Timeline**: several tracks, drag to arrange, trim, split, ripple delete, snapping, zoom, and
  each clip's sound drawn as a waveform so a cut can be made on what you hear.
- **Markers**: M marks this moment on the timeline, Shift+M names it and picks its colour, and
  the comma and full stop keys walk between them. Clips snap to markers, and the flags are saved
  with the project.
- **Clips**: speed, volume, fade in and out, pan and zoom (Ken Burns), crop, mute, and colour
  changes — brighter, darker, contrast, black and white — with keyframes.
- **Chroma key**: key a green or blue background out of a clip, with tolerance, softness and an
  edge setting, so what is under it on the timeline shows through.
- **Between clips**: transitions with a duration you choose.
- **Text**: titles, captions and lower thirds.
- **Subtitles**: import an .srt and it becomes captions on the Titles track, trimmed and styled
  like any clip and burned into the picture on export; write the captions back out as an .srt.
- **Sound**: a music bed that ducks under speech, and a level meter on the transport bar showing
  the output while it plays.
- **Preview**: play it at full, half or quarter size, and make small copies of big videos to edit
  through (the originals are what every export uses).
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
