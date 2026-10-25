class SubtitleError(ValueError):
    """A known subtitle track could not be downloaded or validated."""
    def __init__(self, message: str, refresh_required: bool = False) -> None:
        super().__init__(message)
        self.refresh_required = refresh_required
