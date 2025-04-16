import json
import os
import sys


def configure(settings_file):
    config = {
        'temporary-directory-path': "",
        'default-asset-type': "",
        'citation-database': {
            'username': "",
            'password': "",
            'host': "",
            'dbname': "",
            'schemaname': "",
        },
        'services': [
        ],
        'doi-groups': [
        ],
    }
    service = {
        'longname': "",
        'title': "",
        'api-url': "",
        'api-key': "",
    }
    services = {}
    doi_group = {
        'id': "",
        'publisher': "",
        'db-table': "",
        'doi-query': {
        },
    }
    doi_query_db = {
        'db-query': "",
    }
    doi_query_api = {
        'api-query': {
            'url': "",
            'response': {
                'doi': "",
                'publisher': "",
                'asset-type': "",
            },
            'pagination': {
                'page-count': "",
                'page-number': "",
            },
        },
    }
    print("Creating 'local_settings.py' ...")
    with open(settings_file, "r") as f:
        lines = f.read().splitlines()

    for line in lines:
        if line[0] != '#':
            parts = [x.strip() for x in line.split("=")]
            if parts[0] in config:
                config[parts[0]] = parts[1]
            elif parts[0].find("citation_database") == 0:
                cparts = parts[0].split("-")
                config['citation-database'][cparts[1]] = parts[1]
            elif parts[0].find("service") == 0:
                cparts = parts[0].split("_")
                if cparts[1] == "id":
                    services.update({parts[1]: service.copy()})
                elif cparts[1] in service:
                    idx = parts[1].find(":")
                    sid = parts[1][0:idx]
                    if sid in services:
                        services[sid][cparts[1]] = parts[1][idx+1:]

                else:
                    pass

            else:
                pass

    for key in services.keys():
        config['services'].append({'id': key} | services[key])

    with open(os.path.join(os.path.dirname(__file__), "local_settings.py"),
              "a") as f:
        f.write("config = " + json.dumps(config, indent=4) + "\n")

    print("... done.")
    sys.exit(0)
