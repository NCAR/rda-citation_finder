import json
import os
import requests
import sys
import time

from pathlib import Path

from .inserts import insert_citation
from .local_settings import config
from .utils import db_connect


API_URL = "https://api.elsevier.com/content/search/scopus"


def get_publisher_fixups(**kwargs):
    try:
        conn, err = db_connect()
        if conn is None:
            raise RuntimeError(err)

        cursor = conn.cursor()
        cursor.execute(
                "select original_name, fixup from citation.publisher_fixups")
        return cursor.fetchall()
    except Exception as err:
        kwargs['output'].write(f"***UNABLE TO GET PUBLISHER FIXUPS: '{err}'\n")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()


def find_citations(**kwargs):
    api_key = config['services']['scopus']['api-key']
    params = {'start': 0,
              'field': "prism:doi,prism:url,prism:publicationName,"
                       "prism:coverDate,prism:volume,prism:pageRange,"
                       "prism:aggregationType,prism:isbn,dc:title",
              'httpAccept': "application/json", 'apiKey': api_key}
    publisher_fixups = get_publisher_fixups(output=kwargs['output'])
    for doi, publisher, asset_type in kwargs['doi_list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        total_results = 0x7fffffff
        while params['start'] < total_results:
            filename = (doi.replace("/", "@@") + ".elsevier." +
                        str(params['start']) + ".json")
            filename = os.path.join(config['temporary-directory-path'],
                                    filename)
            if os.path.exists(filename):
                with open(filename, "r") as f:
                    j = json.load(f)

            else:
                params['query'] = "ALL:" + doi
                num_tries = 0
                while num_tries < 3:
                    time.sleep(num_tries * 5)
                    try:
                        response = requests.get(API_URL, params=params)
                        j = json.loads(response.text)
                        if 'service-error' not in j:
                            with open(filename, "w") as f:
                                f.write(response.text)

                            break

                    except Exception:
                        Path(filename).unlink(missing_ok=True)

                    num_tries += 1

                if num_tries == 3:
                    kwargs['output'].write(
                            f"Error reading Scopus JSON for DOI '{doi}': "
                            f"filename: '{filename}', params: '{params}'\n")
                    continue

            if 'error-response' in j:
                Path(filename).unlink(missing_ok=True)
                ecode = j['error-response']['error-code']
                if ecode == "TOO MANY REQUESTS":
                    kwargs['output'].write(
                            "***ABORTING DUE TO RATE LIMITING\n")
                    return
                else:
                    kwargs['output'].write(
                            f"      Error: '{ecode}' at {params['start']}\n")
                    continue

            total_results = int(j['search-results']['opensearch:totalResults'])
            if total_results == 0:
                break

            params['start'] += int(
                    j['search-results']['opensearch:itemsPerPage'])
            for entry in j['search-results']['entry']:
                # get the "works" DOI
                try:
                    works_doi = entry['prism:doi'].replace("\\/", "/")
                except Exception:
                    continue

            success, new_entry = insert_citation(doi, works_doi, "Scopus",
                                                 **kwargs)
            if not success:
                continue

            if new_entry:
                pass
