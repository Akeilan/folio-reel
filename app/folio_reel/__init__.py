"""Folio Reel: a video editor — clips on a timeline, titles, music, export to a file you can share."""
import os

VERSION = "0.5.0"
APP_NAME = "Folio Reel"
APP_ID = "org.folio.Reel"
SHARE = os.environ.get("FOLIO_REEL_SHARE") or "/usr/share/folio-reel"
