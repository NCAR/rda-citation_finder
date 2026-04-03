def convert_unicodes(s):
    s = (s.replace(r"\u00a0", " ")
          .replace(r"\u2010", "-")
          .replace(r"\u2013", "-")
          .replace(r"\u2014", "-")
          .replace(r"\u2019", "'"))
    return s


def unicode_escape(s):
    escaped_string = ""
    escaped = False
    for c in s:
        code = ord(c)
        if code < 0x80:
            escaped_string += c
        elif code < 0xff:
            escaped_string += fr"\u00{code:02x}"
            escaped = True
        else:
            escaped_string += fr"\u{code:04x}"
            escaped = True

    if escaped:
        return convert_unicodes(escaped_string)

    return escaped_string


def add_authors_to_db(author_list, ident, db_conn):
    cursor = db_conn.cursor()
    id, id_type = ident
    seqno = 0
    do_commit = False
    for author in author_list:
        if (((id_type == "DOI" and author['creatorType'] == "author") or
                (id_type == "ISBN" and author['creatorType'] == "editor"))
                and 'lastName' in author and len(author['lastName']) > 0):
            parts = author['firstName'].split()
            fname = unicode_escape(parts[0])
            if len(parts) > 1:
                mname = unicode_escape(parts[1])
            else:
                mname = ""

            do_commit = True
            cursor.execute((
                    "insert into citation.works_authors values (%s, %s, %s, "
                    "%s, %s, NULL, %s) on conflict do nothing"),
                    (id, id_type, unicode_escape(author['lastName']),
                     fname, mname, seqno))
            seqno += 1

    if (do_commit):
        db_conn.commit()
    else:
        print("*** NO INSERTABLE AUTHORS for '{}'".format(ident))
