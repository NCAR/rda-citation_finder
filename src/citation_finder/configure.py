import copy
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
        'services': {
        },
        'doi-groups': {
        },
    }
    service = {
        'longname': "",
        'title': "",
        'api-url': "",
        'api-key': "",
    }
    doi_group = {
        'publisher': "",
        'db-table': "",
        'doi-query': {
        },
    }
    doi_query_db = {
        'db': "",
    }
    doi_query_api = {
        'api': {
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
            idx = line.find("=")
            if idx < 0:
                raise RuntimeError("bad setting on line '{}'".format(line))

            key = line[0:idx].strip()
            value = line[idx+1:].strip()
            if key in config:
                config[key] = value
            elif key.find("citation-database") == 0:
                cparts = key.split("_")
                config['citation-database'][cparts[1]] = value
            else:
                kparts = key.split("_")
                if kparts[-1] == "id":
                    if kparts[0] == "service":
                        d = service
                    elif kparts[0] == "doi-group":
                        d = doi_group
                    else:
                        raise UnboundLocalError("no object defined for '{}'"
                                                .format(kparts[0]))

                    config[kparts[0]+"s"].update({value: copy.deepcopy(d)})
                else:
                    idx = value.find(":")
                    gid = value[0:idx]
                    value = value[idx+1:]
                    gname = kparts[0] + "s"
                    if gname in config:
                        if gid in config[gname]:
                            config[gname][gid][kparts[-1]] = value
                        else:
                            print("Warning: bad setting on line '{}' ignored"
                                  .format(line))

                    elif kparts[0] == "doi-query":
                        if gid not in config['doi-groups']:
                            print("Warning: bad setting on line '{}' ignored"
                                  .format(line))
                            continue

                        if kparts[1] == "api":
                            config['doi-groups'][gid]['doi-query'] = (
                                   copy.deepcopy(doi_query_api))
                            (config['doi-groups'][gid]['doi-query']['api']
                                   ['url']) = value
                        elif kparts[1] == "db":
                            config['doi-groups'][gid]['doi-query'] = (
                                    copy.deepcopy(doi_query_db))
                            config['doi-groups'][gid]['doi-query']['db'] = (
                                    value)
                        else:
                            raise ValueError("invalid setting name '{}'"
                                             .format(key))

                    elif kparts[0][0:4] == "api-":
                        if (not config['doi-groups'].get(gid) or not
                                config['doi-groups'][gid].get('doi-query') or
                                not (config['doi-groups'][gid]['doi-query'])
                                .get('api') or not
                                (config['doi-groups'][gid]['doi-query']['api']
                                 .get(kparts[0][4:]))):
                            print("Warning: bad setting on line '{}' ignored"
                                  .format(line))
                            continue

                        (config['doi-groups'][gid]['doi-query']['api']
                               [kparts[0][4:]][kparts[1]]) = value

    with open(os.path.join(os.path.dirname(__file__), "local_settings.py"),
              "a") as f:
        f.write("config = " + json.dumps(config, indent=4) + "\n")

    print("... done.")
    sys.exit(0)
