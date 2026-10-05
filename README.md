# underglow-daily

The day's codex.comics post, for Underglow, a game in
development. The game reads <https://ricky-zombie.github.io/underglow-daily/latest.json> as play
starts and every three hours while it runs, and puts the post's first image on a bus stop's lightbox ad.

Everything here is public, like the posts themselves.

## Publishing a day

After the day's post is ready for Instagram, from a clone of this repo:

```
python3 publish.py path/to/post.png --title "The day's title" --link https://www.instagram.com/p/...
```

- Give the post's images in order. The game shows the first.
- PNG or JPEG, up to 8 MB and 4096 px a side.
- The lightbox is portrait, 1.2 x 1.73 m (about 0.69 : 1). A 4:5 post fills its width, with thin bands
  above and below in the colour of the image's top-left corner.
- It copies the images into `days/<date>/`, rewrites `latest.json`, drops days older than two weeks
  (git keeps them), then commits and pushes.
- `--date YYYY-MM-DD` publishes for another day (the default is today). `--no-push` commits without pushing.
- `python3 publish.py --clear` takes the comic down, and the game goes back to its stock ad.

It needs only Python 3 and git: a git name and email, and push access to this repo.

## Push access

Whatever runs `publish.py` needs to push here, and to nothing else:

- On a machine signed in to GitHub as ricky-zombie (`gh auth login`), it already can.
- Anywhere else, add a **deploy key** with write access (the repo's Settings → Deploy keys): an SSH key
  that works for this one repo. Or use a fine-grained personal access token limited to this repository,
  with Contents read and write.

Keep the key or token in the agent's own secret settings, never in this repo.

## The feed

`latest.json`:

```json
{
  "version": 1,
  "date": "2026-10-04",
  "title": "The day's title",
  "link": "https://www.instagram.com/p/...",
  "images": ["days/2026-10-04/01-3f9a0c1d2e4b.png"]
}
```

- Image paths are relative to this folder, and the game reads nothing outside it.
- Each file name carries a hash of the image, so a corrected re-run is a new address and the game fetches it.
- An empty `images` list means no comic.
- The game keeps the last image it fetched, so it still shows the comic offline.
