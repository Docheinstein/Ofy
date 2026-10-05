"""Ofy: MusicBrainz-tagged offline music from YouTube Music."""

__version__ = "0.1.0"


def main() -> None:
    import uvicorn

    from ofy.config import env

    uvicorn.run("ofy.main:app", host=env.host, port=env.port, log_level="info")
