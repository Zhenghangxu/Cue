I would like to create a reliable and user-friendly local based web app that will automatically create subtitles for given video on web dev. The idea is to try to not download a full video / audio directly from web dev.

So the entire flow would be like this: If there is a matching eng/chinese subtitle already on open subtitle, we will download it and try to do the matching. If you cannot find a eng/chinese dual subtitle for it, we will just try to use the given AI endpoint to translate the already exists English subtitle to English Chinese dual subtitle, and do the matching.

Search here for docs on opensubtitles: `https://opensubtitles.stoplight.io/docs/opensubtitles-api`

## The END GOAL

when user selected a video file in the app browser, click start, it will execute a full flow to produce a susbtile file with a matching name, and upload it to the same directory location as the video file. Subtitle should be **english / chinese** dual subtitle OR **chinese** single subtitle

Pleaes check `.env` for credential access. When you explore. DO NOT browse file outside of `WEBDAV_SCAN_PATH`, this is to protect privacy of user.

When you do AI translate, make sure you optimize for token efficiency and cost. Make sure you manage your contacts wisely and start a new session whenever possible. 

--

## Subtitle Matching

### IMPORTANT!!
1. We should try to avoid download the full video / audio from WebDAV, slice a 5min audio for matching should be enough:

### OVERALL IDEA

See **suggested** process below:

Given a subtitle file m, cut a short audio track b from movie A, and then automatically align m based on the audio information from b.

---

Specialized Subtitle Synchronization Tools (Most Recommended)

These tools are designed exactly for this task and are very user‑friendly, even for non‑developers.

· ffsubsync – Automatically fixes subtitle offsets by analyzing the audio’s speech features. Just run:
  ffsubsync video.mp4 -i subtitle_to_sync.srt -o output.srt
  Supports SRT, ASS, and other formats.
· autosubsync – Similar to ffsubsync. Usage:
  autosubsync video_file input_subtitle output_subtitle
· Sushi – Great for syncing subtitles from one video version (e.g., Blu‑ray) to another (e.g., TV). It compares the audio similarity between the two versions to calculate the offset.

---

Important: Before using any of these tools, make sure you have FFmpeg installed on your computer, as most of them rely on it to process audio and video.

---

GIVEN A file name, How to associated it with a specific movie / episode? This is required to generate a search query to open subtitle

---

· Regular expressions: essentially extremely flexible "fuzzy search" rules. For example, using a pattern like S(\d+)E(\d+), you can accurately extract "season=1" and "episode=1" from Game.of.Thrones.S01E01....

· Dedicated parsing libraries (RECOMMENDED): more powerful than hand‑written rules. They come with hundreds of built‑in rules and can automatically handle all kinds of complex cases. Commonly used libraries include `GuessIt`, `FileBot`, and `@ctrl/video‑filename‑parser`.

These parsing libraries can directly take a filename like Game.of.Thrones.S01E01.720p.HDTV.x264‑CTU and turn it into structured information, such as title Game of Thrones, season 1, episode 1, resolution 720p, and so on.


LEGALITY NOTE: We are a university program dedicated to preserve old movies digitally. This is for educational and research purpose only!
