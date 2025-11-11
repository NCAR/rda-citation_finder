import json
import os
import psycopg2
import requests
import string
import sys

from .local_settings import config


ignore_words = {
    "a", "an", "and", "from", "in", "of", "on", "that", "the", "them", "they",
    "this", "those", "to",
    "continuing",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
    "nov", "dec",
}


def clean_word(word):
    while (len(word) > 0 and word[-1] not in string.ascii_letters and word[-1]
           not in string.digits):
        word = word[0:-1]

    return word


def build_terms(asset_title, asset_type):
    print("TITLE: " + asset_title)
    wordlist = []
    words = asset_title.split()
    for word in words:
        word.strip()
        if word.lower() not in ignore_words or asset_type == "text":
            word = clean_word(word)
            if len(word) > 0 and (asset_type != "dataset" or word.isalnum()):
                wordlist.append(word)

    return wordlist


def process_id(asset_id, cursor):
    if asset_id[0] == 'd' and asset_id[1:].isnumeric():
        cursor.execute((
                "select doi from dssdb.dsvrsn where dsid = %s and status = "
                "'A'"), (asset_id, ))
        doi = cursor.fetchone()
        if doi is None:
            raise RuntimeError("DOI not found for '{}'".format(asset_id))

        doi = doi[0]
        doi_group = "rda"
        asset_type = "dataset"
        cursor.execute("select title from search.datasets where dsid = %s",
                       (asset_id, ))
        asset_title, = cursor.fetchone()
        query_terms = build_terms(asset_title, asset_type)
    else:
        doi = asset_id
        doi_group = None
        resp = json.loads(
                requests.get(
                        os.path.join("https://api.datacite.org/dois",
                                     asset_id)).content)
        attrs = resp['data']['attributes']
        asset_type = attrs['types']['resourceTypeGeneral'].lower()
        query_terms = build_terms(attrs['titles'][0]['title'], asset_type)
        query_terms.extend(
                [author['familyName'] for author in attrs['creators']])
        query_terms.extend([attrs['publicationYear'], "ucar"])
        if attrs['publisher'].find("Earth Observing") > 0:
            doi_group = "eol"
            query_terms.append(asset_id)
        else:
            doi_group = "ucar"

    return (doi, doi_group, asset_type, query_terms)


def main():
    if len(sys.argv) < 2:
        tool_name = sys.argv[0][sys.argv[0].rfind("/")+1:]
        print((
            "usage: {} [-n <max_pages>] <dnnnnnn | DOI>".format(tool_name) +
            "\n"
            "options:\n"
            "-n <max_pages>  only process <max_pages> pages from the search "
            "results\n"
        ))
        sys.exit(1)

    asset_id = sys.argv[-1]
    if len(sys.argv) == 4 and sys.argv[2] == "-n":
        max_pages = int(sys.argv[3])
    else:
        max_pages = 0x7fffffff

    try:
        db_config = {k: v for k, v in config['citation-database'].items() if
                     k != "schemaname"}
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        doi, doi_group, asset_type, qterms = process_id(asset_id, cursor)
        print(", ".join([doi, str(doi_group), asset_type, str(qterms)]))
        print(config['doi-groups'][doi_group]['db-table'])
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    main()
