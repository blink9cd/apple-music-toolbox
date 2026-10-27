-- The invented phone's music database, for the samples folder's fake afcclient,
-- which builds the database from this text at each copy: no binary is committed.
-- Only the tables and columns phone_audit reads, under the phone's own names.
-- Track 1 has its file; track 2 has none on the phone; track 3's file is another size;
-- the purchased row's base location is outside the sync.
CREATE TABLE base_location (base_location_id INTEGER PRIMARY KEY, path TEXT);
CREATE TABLE item (item_pid INTEGER PRIMARY KEY, base_location_id INTEGER,
  album_pid INTEGER, item_artist_pid INTEGER, disc_number INTEGER, track_number INTEGER);
CREATE TABLE item_extra (item_pid INTEGER PRIMARY KEY, location TEXT,
  file_size INTEGER, title TEXT);
CREATE TABLE album (album_pid INTEGER PRIMARY KEY, album TEXT);
CREATE TABLE item_artist (item_artist_pid INTEGER PRIMARY KEY, item_artist TEXT);

INSERT INTO base_location VALUES (1, 'iTunes_Control/Music/F00');
INSERT INTO base_location VALUES (2, 'iTunes_Control/Music/F01');
INSERT INTO base_location VALUES (3, 'iTunes_Control/Purchases');
INSERT INTO album VALUES (1, 'Invented Album');
INSERT INTO album VALUES (2, 'Purchased Placeholder Album');
INSERT INTO item_artist VALUES (1, 'The Placeholder Band');
INSERT INTO item_artist VALUES (2, 'The Made-Up Trio');
INSERT INTO item VALUES (1, 1, 1, 1, 1, 1);
INSERT INTO item_extra VALUES (1, 'AAAA.mp3', 4096, 'First Placeholder');
INSERT INTO item VALUES (2, 1, 1, 1, 1, 2);
INSERT INTO item_extra VALUES (2, 'BBBB.mp3', 4096, 'Second Placeholder');
INSERT INTO item VALUES (3, 2, 1, 1, 1, 3);
INSERT INTO item_extra VALUES (3, 'CCCC.m4a', 8192, 'Third Placeholder');
INSERT INTO item VALUES (4, 3, 2, 2, 1, 1);
INSERT INTO item_extra VALUES (4, 'DDDD.m4a', 1024, 'Purchased Placeholder');
