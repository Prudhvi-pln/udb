# Changelog

## Version 2.14.8 [2025-08-04]
- Removed obsolete clients.
- Added a configuration setting to allow displaying more search results. Specify `search_limit` in the client-specific configuration in your yaml file.
- Fix #56: Added url redirects for http.client mode.

## Version 2.14.7 [2025-04-30]
- KissKhClient: Fix #39: Added missing decryption for subtitles.
- KissKhClient: Fix #42: Updated domain.
- KissKhClient: Fix #42: Compatability with ffmpeg 2025 version.
- Fix #45: Fetch Google Chrome version in MacOS.
- Few bug fixes.

## Version 2.14.3 [2025-02-21]
- AnimePaheClient: Removed dependency on jsbeautifier module.
- KissKhClient: Fix erroring out on upcoming episodes.
- KissKhClient: Update subtitle decryption functions with new decyption logic.
- KissKhClient: Fix for new security check.
- New cli option `-H` to show hidden/unmanaged clients.

## Version 2.14.0 [2025-01-18]
- Hello World! A lot happened since the last version and almost every pirate site is taken down ☹️. But, I'm back with a new update 🙂.
- Replaced MyAsianTVClient with AsianDramaClient, which is operational but no updates after Nov 24, 2024.
- New KissKhClient 🎉 serving all your needs: Anime, Drama, Movies, TV Shows (almost everything).

## Version 2.13.4 [2024-07-26]
- F2CloudClient: Added new client for F2Cloud (formerly Vidplay) under Vidsrc.
- IMDBClient: Introduced a new search client using IMDB. The default search remains TMDB, but IMDB will be used as a fallback when TMDB is unreachable.
- SuperembedClient: Improved speed when loading episodes of a selected series.
- SuperembedClient: [BETA] Fix captcha issues. _This is not a stable feature_.

## Version 2.13.2 [2024-07-11]
- DramaClient: Fixed search for Upcoming dramas.
- Simplified configuration to ensure it remains static and user-specific.
- Added support for multiple instances of UDB with seamless logging. Use cli option `-l <log-name>` for custom log file name.
- Addressed few depreciation warnings for Python >= 3.12

## Version 2.13.1 [2024-06-29]
- Updated Changelog. Added feature to view the changelog from UDB before updating.
- Fix #21: Fixed bug while parsing subtitles in Superembed Client.
- VidplayClient: Using a new reliable external source for Vidplay keys which updates every hour. Thanks to [KillerDogeEmpire](https://github.com/KillerDogeEmpire) for the awesome repo ❤️.
- Feature #15: Added new Superembed Client for Movies & TV Shows. Better alternative to Vidsrc with large catalog and better stability.
- VidplayClient: Recursive approach to fetch vidplay keys for faster updates. Now looks at PRs as well.
- Fix #20: Change in Vidplay source id.
- Many other performance tweaks under the hood.

## Version 2.12.4 [2024-06-16]
- Fix #18: Page not found during search results
- Added recursive input for user prompts and whole UDB to avoid hassle of reloading from the start.
- Updated TMDB Client: Removed dependency on vidsrc while displaying search results.
- Updated HLS Downloader: Skip non-downloadable subtitles for Movies/Series.
- Fixed HLS Downloader: Unable to download series with special characters like '#'.
- Simplified Configuration file.
- Other Minor Bug Fixes and performance improvements.

## Version 2.12.2 [2024-04-20]
- New Feature #11: Support for Movies & TV Shows is finally here.
- AnimePahe: Reload saved cookies for faster loading.
- Several optimizations under the hood.

## Version 2.11.6 [2024-03-24]
- Fix update issue - unable to retrieve info from Git
- Dynamically fetch the cdn url for GogoAnime Client instead of config file.
- Updated GogoAnime Link in Config.
- Corrected few typos.

## Version 2.11.3 [2024-02-11]
- Feature: Display download size of stream video files. The accuracy of size estimation can be tuned by setting -hsa [percent]. Disabled by default.
- Feature: Select specific episodes in addition to a range of episodes. Examples of valid inputs: 1,3,5 | 1-4,6 | 5 | 1-5 | 1- | -3
- Added License & Updated Readme (with UDB demo)
- Fix minor bug in DramaClient

## Version 2.11.2 [2024-01-28]
- Implemented Feature #8: Support for GogoAnime.
- The UDB interface is now vibrant with colors. Explore the enhanced cli visual experience!
- Introduced an option to update UDB directly within the application.
- Added a new feature to display video duration information.
- Included performance enhancements and addressed minor bugs for a smoother user experience.

## Version 2.10.6 [2024-01-18]
- Fix #9: import error for Crypto.Cipher with pycryptodome. Replaced pycryptodome with pycryptodomex.

## Version 2.10.5 [2024-01-17]
- Fix #7: Bypass DDoS check in AnimePahe (requires undetected chromedriver)
- Show total episodes count for a drama in search results
- Minor bug fixes

## Version 2.10.3 [2023-11-06]
- Updated Anime Client as per new APIs
- Updated Drama Client to fetch single m3u8 links
- Optimized HLS Downloader to fetch segment links

## Version 2.10.0 [2023-10-07]
- Added new Downloader for non-m3u8 links 🎉
- Fixed #5
- Optimized Downloader under the hood

## Version 2.9.0 [2023-10-06]
- Changed to Semantic versioning
- Implemented version check
- Bug fixes #4 #5
- Show skipped episodes in download summary

## Version 2.8 [2023-10-04]
- Added detailed loggers to make it developer friendly :)
- Updated drama links
- Get stream links dynamically
- Updated _fetch_episodes_list_ in Drama to load episodes > 50
- Added option to auto select from available resolutions
- Performance optimizations under the hood

## Version 2.7 [2023-06-05]
- Added CLI support for automation. Run this command for details: `python udb.py -h`
- Added dynamic output declaration
- Fixed downloading of floating episodes (ex: 6.5, 10.5)

## Version 2.6 [2023-05-20]
- Added Linux OS compatibility
- Fixed unable to load X.5 episodes

## Version 2.5 [2023-04-12]
- Modified anime client as per updated animepahe site
- Added support for backup url in Dramas
- Added support for non-ts m3u8 urls
- Add preferred & blacklist of m3u8 links
- Removed dependency on openssl. Uses pycryptodome instead

## Version 2.0 [2023-02-11]
- Rewritten code completely
- Added support to download drama. Finally.. ^_^
- Added support to retrieve paginated episodes from AnimePahe
- Added headers & custom retry decorator while downloading segments to avoid Connection Reset Error
- Generalized parallel downloader
- Added Progress bar for downloads using tqdm

## Version 1.5 [2023-02-02]
- All new downloader. Custom implementation of m3u8 downloader and reliable m3u8 parser

## Version 1.2 [2023-01-29]
- Fix m3u8 link parser. Bug fixes

## Version 1.1 [2023-01-28]
- First version
- Download multiple anime episodes in parallel from animepahe
