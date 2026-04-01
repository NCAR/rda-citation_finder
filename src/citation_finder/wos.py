import json
import os
import requests
import time

from .local_settings import config


API_URL = "https://wos-api.clarivate.com/api/wos"


def process_works_id(works_id, **kwargs):
    headers = {'X-ApiKey': config['services']['wos']['api-key']}
    params = {'databaseId': "WOS", 'count': 1, 'firstRecord': 1,
              'viewField': "identifiers"}
    if not kwargs['no_works']:
        params['viewField'] += "+names+titles+pub_info"

    # get the data for each work


def find_citations(**kwargs):
    headers = {'X-ApiKey': config['services']['wos']['api-key']}
    wos_id_params = {'databaseId': "DCI", 'count': 1, 'firstRecord': 1,
                     'viewField': "none"}
    for doi, publisher, asset_type in kwargs['doi_list']:
        kwargs['output'].write(
                f"    querying DOI '{doi} | {publisher} | {asset_type}' ...\n")
        # get the WoS ID for the DOI
        wos_id_params['usrQuery'] = f"DO={doi}"
        response = requests.get(API_URL, headers=headers, params=wos_id_params)
        try:
            j = json.loads(response.text)
        except Exception:
            kwargs['output'].write(
                    f"WoS response for DOI '{doi}' ID is not JSON\n")
            continue

        if (response.status_code == 429 and 'code' in j and j['code'] ==
                "Throttle Error"):
            kwargs['output'].write(
                    "    ***ABORTING due to throttle error\n")
            break

        try:
            response.raise_for_status()
        except Exception as err:
            kwargs['output'].write("HTTP error {} for DOI '{}': '{}'\n".format(
                    response.status_code, doi, err))
            continue

        try:
            wos_id = j['Data']['Records']['records']['REC'][0]['UID']
        except Exception:
            kwargs['output'].write("      No WoS ID found")
            continue

        if len(wos_id) == 0:
            kwargs['output'].write("      Empty WoS ID found")
            continue

        kwargs['output'].write(f"      WoS ID: '{wos_id}'\n")
        # get the WoS IDs for the "works" that have cited this DOI
        works_ids = []
        works_id_params = {'databaseId': "WOS", 'uniqueId': wos_id,
                           'count': 100, 'firstRecord': 1, 'viewField': ""}
        num_records = 2
        while works_id_params['firstRecord'] < num_records:
            time.sleep(0.6)
            response = requests.get(os.path.join(API_URL, "citing"),
                                    headers=headers,
                                    params=works_id_params)
            try:
                j = json.loads(response.text)
            except Exception:
                kwargs['output'].write(
                        "WoS response for citing works for DOI/WoS_ID "
                        f"'{doi}/{wos_id}' is not JSON\n")
                works_id_params['firstRecord'] = num_records
                continue

            for id in j['Data']['Records']['records']['REC']:
                works_ids.append(id['UID'])

            num_records = j['QueryResult']['RecordsFound']
            works_id_params['firstRecord'] += works_id_params['count']

        kwargs['output'].write(
                f"        {len(works_ids)} citations found ...\n")
        for works_id in works_ids:
            process_works_id(works_id, **kwargs)
