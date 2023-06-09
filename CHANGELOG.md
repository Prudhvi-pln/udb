## Changelog
 - Version 2.7 [2023-06-05]
   - Added CLI support for automation. Run this command for details: `python udb.py -h`
   - Added dynamic output declaration
   - Fixed downloading of floating episodes (ex: 6.5, 10.5)

 - Version 2.6 [2023-05-20]
   - Added Linux OS compatibility
   - Fixed unable to load X.5 episodes

 - Version 2.5 [2023-04-12]
   - Modified anime client as per updated animepahe site
   - Added support for backup url in Dramas
   - Added support for non-ts m3u8 urls
   - Add preferred & blacklist of m3u8 links
   - Removed dependency on openssl. Uses pycryptodome instead

 - Version 2.0 [2023-02-11]
   - Rewritten code completely
   - Added support to download drama. Finally.. ^_^
   - Added support to retrieve paginated episodes from AnimePahe
   - Added headers & custom retry decorator while downloading segments to avoid Connection Reset Error
   - Generalized parallel downloader
   - Added Progress bar for downloads using tqdm

 - Version 1.5 [2023-02-02]
   - All new downloader. Custom implementation of m3u8 downloader and reliable m3u8 parser

 - Version 1.2 [2023-01-29]
   - Fix m3u8 link parser. Bug fixes

 - Version 1.1 [2023-01-28]
   - First version
   - Download multiple anime episodes in parallel from animepahe
