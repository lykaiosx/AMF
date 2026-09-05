AMF 4.4

IMPORTED TORRENT TITLE RESOLUTION
=================================

Problem fixed:
A pasted URL such as:

    https://nyaa.si/download/1960266.torrent

used to appear in Cart simply as:

    1960266

AMF 4.4 resolves the actual torrent/release title.


TITLE RESOLUTION ORDER
----------------------
1. Magnet link:
       uses the magnet's dn= display name.

2. Local .torrent:
       reads info.name / info.name.utf-8 from torrent metadata.

3. HTTP/HTTPS .torrent URL:
       AMF downloads the small torrent metadata and reads info.name.

4. Provider detail-page fallback:
       for Nyaa, AMF automatically maps:

       /download/1960266.torrent
       -> /view/1960266

       and reads the real page title.

5. Only if every lookup fails does AMF retain the old URL-derived fallback.


NEW CART BUTTON
---------------
Resolve Titles

If you already have numeric items such as:
    1960266
    1322498
    854600

select them and click Resolve Titles.

If nothing is selected, AMF resolves every placeholder/numeric imported title
in the Cart.


BULK IMPORT
-----------
Paste List and Import Files now automatically resolve torrent names BEFORE the
new items are added to the Cart.

Resolution runs concurrently with a progress window so a large list is much
faster than resolving links one at a time.


UPDATES / USER STATE
--------------------
The AMF 4.3 persistence fix remains active:

- config.json is not rewritten by Setup
- cart.json is not rewritten by Setup
- imported/custom sources remain preserved
- Nyaa, 1377x and YTS remain permanent baseline sources

Run Setup.exe to update AMF in place.
