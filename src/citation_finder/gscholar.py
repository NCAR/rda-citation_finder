import json
import os
import psycopg2
import requests
import string
import subprocess
import sys
import time

from . import utils
from .local_settings import config
from datetime import datetime, timedelta
from multiprocessing import Manager, Process


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

    word = word.replace("/", "%2f")
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
        query_terms.extend(["ucar",
                            "(" + asset_id + " OR ds" + asset_id[1:4] + "." +
                            asset_id[6] + ")"])
        serp_param = "q"
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
        query_terms.extend([str(attrs['publicationYear']), "ucar"])
        if attrs['publisher'].find("Earth Observing") > 0:
            doi_group = "eol"
            query_terms.append(asset_id)
        else:
            doi_group = "ucar"

        if asset_type == "text":
            print(config['services']['gscholar']['api-url'] + "?engine=google_scholar&q=" + ("+").join(query_terms) + "&api_key=" + config['services']['gscholar']['api-key'])
            serp_param = "cites"
        else:
            serp_param = "q"

    return (doi, doi_group, asset_type, serp_param, query_terms)


def start_translation_server():
    o = subprocess.run(("/bin/tcsh -c 'module load podman; podman image pull "
                        "-q docker://dattore/translation-server > /dev/null; "
                        "podman run -d -p 1969:1969 "
                        "dattore/translation-server'"),
                       shell=True, capture_output=True)
    if o.returncode == 0:
        # give the container time to run its startup script
        time.sleep(15)
        return o.stdout.decode("utf-8")[0:12]
    else:
        print(("Error starting translation server: '{}'")
              .format(o.stderr.decode("utf-8")))
        sys.exit(1)


def check_for_translation_server():
    o = subprocess.run(("/bin/tcsh -c 'module load podman; podman ps |grep "
                        """"dattore/translation-server"'"""), shell=True,
                       capture_output=True)
    if o.returncode == 0:
        return o.stdout.decode("utf-8")[0:12]
    else:
        return start_translation_server()


def do_translation(url, data):
    try:
        data['translation'] = json.loads(
                requests.post(
                        "http://127.0.0.1:1969/web",
                        data=url,
                        headers={'Content-type': "text/plain"}).content)[0]
        del data['error']
    except Exception as e:
        data['error'] = e


def translation(url):
    manager = Manager()
    data = manager.dict({'error': "", 'translation': {}})
    num_try = 0
    while num_try < 5 and 'error' in data:
        p = Process(target=do_translation, args=(url, data))
        p.start()
        max_time = datetime.now() + timedelta(seconds=15)
        while datetime.now() < max_time:
            if not p.is_alive():
                break

        if p.is_alive():
            p.kill()
            print("TIMEOUT trying to translate URL '{}'".format(url))
            data = None
            break

        num_try += 1

    if 'error' in data:
        print((
              "Error: failed to translate URL '{}', error: '{}'")
              .format(url, data['error']))

    return data


def add_work_to_db(works_data, db_conn):
    type_code = None
    if (works_data['itemType'] == "bookSection" and
            utils.inserted_book_chapter_works_data(works_data, db_conn,
                                                   "GoogleScholar")):
        type_code = "C"
    elif (works_data['itemType'] == "journalArticle" and
            utils.inserted_journal_works_data(works_data, db_conn,
                                              "GoogleScholar")):
        type_code = "J"

    if (type_code is not None and not
            utils.inserted_general_works_data(works_data, db_conn, type_code,
                                              "GoogleScholar")):
        type_code = None

    return type_code


def insert_citation(url, translation, data_doi, db_conn):
    work_doi = None
    if 'DOI' in translation:
        work_doi = translation['DOI']
    elif ('extra' in translation and
          translation['extra'][0:5] == "DOI: "):
        work_doi = translation['extra'][5:]

    if work_doi is None:
        return

    print("WORK DOI: " + work_doi)
    utils.add_authors_to_db(translation['creators'], (work_doi, "DOI"),
                            db_conn)
    type_code = add_work_to_db(translation, db_conn)
    if type_code is None:
        print("UNRECOGNIZED WORKS TYPE: '{}, URL:'{}'"
              .format(translation['itemType'], url))
        return

    # insert citation
    if not utils.inserted_citation(data_doi, db_conn):
        return
    # insert source
    utils.insert_source(data_doi, db_conn)


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
        MAX_PAGES = int(sys.argv[3])
    else:
        MAX_PAGES = 1e10

    try:
        db_config = {k: v for k, v in config['citation-database'].items() if
                     k != "schemaname"}
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        doi, doi_group, asset_type, serp_param, qterms = (
                process_id(asset_id, cursor))
        print(", ".join([doi, str(doi_group), asset_type, str(qterms)]))
        print(config['doi-groups'][doi_group]['db-table'])
        print(config)
        print(serp_param)
        request_base = (config['services']['gscholar']['api-url'] +
                        "?engine=google_scholar&" + serp_param + "=" +
                        "+".join(qterms) + "&api_key=" +
                        config['services']['gscholar']['api-key'] +
                        "&num=20&start=")
        current_page = 0
        num_pages = MAX_PAGES
        while current_page < num_pages:
            #resp = json.loads(requests.get(request_base +
            #                               str(current_page*20)).content)
            resp = json.loads('{"organic_results": [{"link": "https://hess.copernicus.org/articles/21/707/2017/"}, {"link": "https://hess.copernicus.org/articles/28/2375/2024/"}], "search_information": {"total_results": 1}, "serpapi_pagination": {"next": 2}}')
            if current_page == 0:
                num_results = resp['search_information']['total_results']
                num_pages = int((num_results + 20) / 20)

            links = []
            for res in resp['organic_results']:
                if 'link' in res:
                    links.append(res['link'])
                else:
                    print(("*** NO LINK for '{}' ({}:{})")
                          .format(res['title'], str(qterms), res['position']))

            podman_id = check_for_translation_server()
            for url in links:
                work = translation(url)
                print(work)
                if work is None or 'translation' not in work:
                    continue

                insert_citation(url, work['translation'], doi, conn)

            if ('serpapi_pagination' in resp and 'next' in
                    resp['serpapi_pagination']):
                current_page += 1
            else:
                current_page = MAX_PAGES

            if current_page >= MAX_PAGES:
                break

    finally:
        if 'conn' in locals():
            conn.close()

        if 'podman_id' in locals():
            subprocess.run((
                    "/bin/tcsh -c 'module load podman; podman kill " +
                    podman_id + "'"), shell=True)


if __name__ == "__main__":
    main()
