"""Version information for MediaWatch.

The version line is maintained by release-please - the marker comment is how
it finds the line. Do not bump it by hand; land a Conventional Commit and
merge the release PR instead.
"""

__version__ = "2.0.0"  # x-release-please-version
# Derived, not duplicated: release-please only rewrites the line above, so a
# hand-maintained tuple would drift away from it on the first release.
__version_info__ = tuple(int(part) for part in __version__.split("."))
__project_name__ = "MediaWatch"
__description__ = "Universal Media Server Monitoring for Discord"
__github_url__ = "https://github.com/nichtlegacy/MediaWatch"
