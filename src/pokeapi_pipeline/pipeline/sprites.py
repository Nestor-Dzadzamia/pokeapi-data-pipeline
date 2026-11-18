from pathlib import Path

FORMATS: dict[str, tuple[str, str]] = {
    "png": ("pngs", "image/png"),
    "gif": ("gifs", "image/gif"),
}


class SpriteParser:
    def __init__(self, sprites_dir: Path, formats: dict[str, tuple[str, str]] = FORMATS):
        self.sprites_dir = Path(sprites_dir)
        self.formats = formats

    def sprite_files(self, pokemon: dict) -> list[dict]:
        """
        every png and gif url in pokemon["sprites"], with the file name it gets on disk and in the bucket.
        ...
        """
        files = []
        links = [((), pokemon["sprites"])]

        while links:
            keys, link = links.pop()

            if isinstance(link, dict):
                links.extend((keys + (key,), value) for key, value in link.items())
                continue

            extension = link.rsplit(".", 1)[-1] if isinstance(link, str) else None
            if extension not in self.formats:  # null urls, svg and webp files are skipped
                continue

            folder, _ = self.formats[extension]
            object_name = f"{pokemon['id']}_{pokemon['name']}/{folder}/{'__'.join(keys)}.{extension}"

            files.append(
                {
                    "pokemon_id": pokemon["id"],
                    "sprite_key": "/".join(keys),
                    "format": extension,
                    "source_url": link,
                    "object_name": object_name,
                    "local_path": str(self.sprites_dir / object_name),
                }
            )

        return sorted(files, key=lambda f: f["sprite_key"])