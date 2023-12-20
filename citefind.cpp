#include <iostream>
#include <fstream>
#include <sstream>
#include <thread>
#include <regex>
#include <unordered_map>
#include <unordered_set>
#include <sys/stat.h>
#include <PostgreSQL.hpp>
#include <json.hpp>
#include <strutils.hpp>
#include <utils.hpp>
#include <tempfile.hpp>
#include <datetime.hpp>

using namespace PostgreSQL;
using std::cerr;
using std::chrono::seconds;
using std::cout;
using std::deque;
using std::endl;
using std::find;
using std::get;
using std::ifstream;
using std::make_tuple;
using std::regex;
using std::regex_search;
using std::stoi;
using std::string;
using std::stringstream;
using std::tie;
using std::this_thread::sleep_for;
using std::to_string;
using std::tuple;
using std::unordered_map;
using std::unordered_set;
using std::vector;
using strutils::append;
using strutils::replace_all;
using strutils::split;
using strutils::sql_ready;
using strutils::substitute;
using strutils::to_lower;
using strutils::to_title;
using strutils::trim;
using unixutils::mysystem2;

string myerror = "";
string mywarning = "";

struct ConfigData {
  struct DOI_Group {
    DOI_Group() : id(), publisher(), db_data(), api_data() { }

    struct DB_Data {
      DB_Data() : host(), username(), password(), doi_query(), insert_table()
      { }

      string host, username, password;
      string doi_query, insert_table;
    };

    struct API_Data {
      struct Response {
        Response() : doi_path(), publisher_path(), asset_type_path() { }

        string doi_path, publisher_path, asset_type_path;
      };

      struct Pagination {
        Pagination() : page_num(), page_cnt() { }

        string page_num, page_cnt;
      };

      API_Data() : url(), response(), pagination() { }

      string url;
      Response response;
      Pagination pagination;
    };

    string id, publisher;
    DB_Data db_data;
    API_Data api_data;
  };

  ConfigData() : tmpdir(), default_asset_type(), doi_groups() { }

  string tmpdir, default_asset_type;
  vector<DOI_Group> doi_groups;
} g_config_data;

struct Args {
  Args() : doi_group(), clean_tmpdir(true), no_works(false) { }

  ConfigData::DOI_Group doi_group;
  bool clean_tmpdir, no_works;
} g_args;

Server g_server;
stringstream g_myoutput, g_mail_message;
unordered_map<string, string> g_journal_abbreviations, g_publisher_fixups;
unordered_set<string> g_journals_no_abbreviation;
const regex email_re("(.)*@(.)*\\.(.)*");
std::ofstream g_output;
string g_single_doi;

typedef tuple<string, string, string> DOI_DATA;
typedef vector<DOI_DATA> DOI_LIST;
typedef tuple<string, string, string, string, bool> SERVICE_DATA;
unordered_map<string, SERVICE_DATA> g_services;

void clean_up() {
  if (g_args.clean_tmpdir) {
    stringstream oss, ess;
    mysystem2("/bin/tcsh -c \"/bin/rm -f " + g_config_data.tmpdir + "/*.json\"",
        oss, ess);
  }
  if (!myerror.empty()) {
    g_mail_message << myerror << endl;
  }
  if (!g_myoutput.str().empty()) {
    g_mail_message << g_myoutput.str() << endl;
  }
  if (!g_mail_message.str().empty()) {
    unixutils::sendmail("dattore@ucar.edu", "dattore@ucar.edu", "", "citefind "
        "cron for " + g_args.doi_group.id, g_mail_message.str());
  }
}

void add_to_error_and_exit(string msg) {
  append(myerror, msg, "\n");
  exit(1);
}

string journal_abbreviation(string journal_name) {
  auto parts=split(journal_name);
  if (parts.size() == 1) {
    return journal_name;
  }
  string abbreviation;
  size_t count=0,last_count=0;
  for (auto& part : parts) {
    if (part.back() == ',' || part.back() == ':' || part.back() == '.') {
      part.pop_back();
    }
    if (last_count > 0) {
      abbreviation+=" ";
    }
    if (g_journal_abbreviations.find(part) != g_journal_abbreviations.end()) {
      abbreviation+=g_journal_abbreviations[part];
      last_count=g_journal_abbreviations[part].length();
      count+=last_count;
    } else {
      abbreviation+=part;
      last_count=part.length();
    }
  }
  if (count > 0) {
    return abbreviation;
  }
  return journal_name;
}

bool inserted_book_data_from_google(string isbn) {
  auto fn_isbn = g_config_data.tmpdir + "/cache/" + isbn + ".google.json";
  struct stat buf;
  if (stat(fn_isbn.c_str(), &buf) != 0) {
    sleep_for(seconds(1));
    stringstream oss, ess;
    mysystem2("/bin/tcsh -c \"curl -s -o " + fn_isbn + " 'https://"
        "www.googleapis.com/books/v1/volumes?q=isbn:" + isbn + "'\"", oss, ess);
    if (!ess.str().empty()) {
      myerror += "\nError retrieving book data from Google";
      return false;
    }
  }
  ifstream ifs(fn_isbn.c_str());
  auto e = myerror;
  JSON::Object isbn_obj(ifs);
  if (!isbn_obj) {
    myerror = e + "\nError reading JSON : '" + myerror + "'";
    stringstream oss, ess;
    mysystem2("/bin/rm " + fn_isbn, oss, ess);
    return false;
  }
  if (isbn_obj["items"][0]["volumeInfo"]["authors"].size() == 0) {
    myerror += "\nEmpty Google data for ISBN : '" + isbn + "'";
    return false;
  }
  for (size_t m = 0; m < isbn_obj["items"][0]["volumeInfo"]["authors"].size();
      ++m) {
    auto sp = split(isbn_obj["items"][0]["volumeInfo"]["authors"][m].
        to_string());
    auto fnam = sp.front();
    string mnam;
    size_t next = 1;
    if (sp.size() > 2) {
      mnam = sp[next++];
    }
    string lnam;
    for (size_t n = next; n < sp.size(); ++n) {
      if (!lnam.empty()) {
        lnam += " ";
      }
      lnam += sp[n];
    }
    if (g_server.insert("citation.works_authors", ("id, id_type, last_name, "
        "first_name, middle_name, sequence"), ("'" + isbn + "', 'ISBN', '" +
        sql_ready(lnam) + "', '" + sql_ready(fnam) + "', '" + sql_ready(mnam) +
        "', " + to_string(m)), "update id_type = values(id_type), sequence = "
        "values(sequence)") < 0) {
      myerror += "\nError while inserting author (" + isbn + ",ISBN," + lnam +
          "," + fnam + "," + mnam + "): '" + g_server.error() + "' from Google "
          "Books";
      return false;
    }
  }
  auto ttl = substitute(isbn_obj["items"][0]["volumeInfo"]["title"].to_string(),
      "\\", "\\\\");
  if (g_server.insert("citation.book_works", "isbn, title, publisher", "'" +
      isbn + "', '" + sql_ready(ttl) + "', '" + isbn_obj["items"][0][
      "volumeInfo"]["publisher"].to_string() + "'", "update title = values("
      "title), publisher = values(publisher)") < 0) {
    myerror += "\nError while inserting book data (" + isbn + "," + ttl + "," +
        isbn_obj["items"][0]["volumeInfo"]["publisher"].to_string() + "): '" +
        g_server.error() + "'";
    return false;
  }
  return true;
}

bool inserted_book_data_from_openlibrary(string isbn) {
  auto fn_isbn = g_config_data.tmpdir + "/cache/" + isbn + ".openlibrary.json";
  struct stat buf;
  if (stat(fn_isbn.c_str(), &buf) != 0) {
    sleep_for(seconds(1));
    stringstream oss, ess;
    mysystem2("/bin/tcsh -c \"curl -s -o " + fn_isbn + " 'https://"
        "openlibrary.org/api/books?bibkeys=ISBN:" + isbn + "&jscmd="
        "details&format=json'\"", oss, ess);
    if (!ess.str().empty()) {
      myerror += "\nError retrieving book data from Open Library";
      return false;
    }
  }
  ifstream ifs(fn_isbn.c_str());
  auto e = myerror;
  JSON::Object isbn_obj(ifs);
  if (!isbn_obj) {
    stringstream oss, ess;
    mysystem2("/bin/rm " + fn_isbn, oss, ess);
    myerror = e + "\nError reading JSON : '" + myerror + "'";
    return false;
  }
  auto o = isbn_obj["ISBN:" + isbn]["details"];
  auto oa = o["authors"];
  if (oa.size() == 0) {
    myerror += "\nEmpty Google data for ISBN : '" + isbn + "'";
    return false;
  }
  for (size_t m = 0; m < oa.size(); ++m) {
    auto sp = split(oa[m]["name"].to_string());
    auto fnam = sp.front();
    string mnam;
    size_t next = 1;
    if (sp.size() > 2) {
      mnam = sp[next++];
    }
    string lnam;
    for (size_t n = next; n < sp.size(); ++n) {
      if (!lnam.empty()) {
        lnam += " ";
      }
      lnam += sp[n];
    }
    if (g_server.insert("citation.works_authors", ("id, id_type, last_name, "
        "first_name, middle_name, sequence"), ("'" + isbn + "', 'ISBN', '" +
        sql_ready(lnam) + "', '" + sql_ready(fnam) + "', '" + sql_ready(mnam) +
        "', " + to_string(m)), "update id_type = values(id_type), sequence = "
        "values(sequence)") < 0) {
      myerror += "\nError while inserting author (" + isbn + ",ISBN," + lnam +
          "," + fnam + "," + mnam + "): '" + g_server.error() + "' from Open "
          "Library";
      return false;
    }
  }
  auto ttl = substitute(o["title"].to_string(), "\\", "\\\\");
  if (g_server.insert("citation.book_works", "isbn, title, publisher", "'" +
      isbn + "', '" + sql_ready(ttl) + "', '" + o["publishers"][0].to_string() +
      "'", "update title = values(title), publisher = values(publisher)") < 0) {
    myerror += "\nError while inserting book data (" + isbn + "," + ttl + "," +
        o["publishers"][0].to_string() + "): '" + g_server.error() + "'";
    return false;
  }
  return true;
}

bool inserted_book_data(string isbn) {
  auto b = inserted_book_data_from_google(isbn);
  if (!b) {
    b = inserted_book_data_from_openlibrary(isbn);
  }
  return b;
}

string repair_string(string s) {
  auto sp = split(s, "\\n");
  if (sp.size() > 1) {
    s.clear();
    for (auto& p : sp) {
      trim(p);
      append(s, p, " ");
    }
  }
  replace_all(s, "\\/", "/");
  replace_all(s, "\\", "\\\\");
  return s;
}

void get_citations(string url, string service_id, size_t sleep, string
    filename, JSON::Object& doi_obj) {
  struct stat buf;
  if (stat(filename.c_str(), &buf) != 0) {
    sleep_for(seconds(3));
    stringstream oss, ess;
    mysystem2("/bin/tcsh -c \"curl -s -o " + filename + " '" + url + "'\"", oss,
        ess);
    if (!ess.str().empty()) {
      myerror += "\nError while getting " + service_id + " citations from '" +
          url + "': '" + ess.str() + "'";
    }
  }
  ifstream ifs(filename.c_str());
  try {
    doi_obj.fill(ifs);
  } catch (...) {
    myerror += "\nunable to create JSON object from file '" + filename + "'";
  }
  ifs.close();
}

string cache_file(string doi) {
  string fnam = doi;
  replace_all(fnam, "/", "@@");
  fnam = g_config_data.tmpdir + "/cache/" + fnam + ".crossref.json";
  struct stat buf;
  if (stat(fnam.c_str(), &buf) != 0) {
    sleep_for(seconds(3));
    stringstream oss, ess;
    mysystem2("/bin/tcsh -c \"curl -s -o '" + fnam + "' 'https://api.crossref."
        "org/works/" + doi + "'\"", oss, ess);
    if (!ess.str().empty()) {
      myerror += "\nError while getting CrossRef data for works DOI '" + doi +
          "': '" + ess.str() + "'";
      mysystem2("/bin/tcsh -c \"/bin/rm -f " + fnam + "\"", oss, ess);
      return "";
    }
  }
  return fnam;
}

bool filled_authors_from_cross_ref(string subj_doi, JSON::Object& obj) {
  auto cfile = cache_file(subj_doi);
  if (!cfile.empty()) {
    ifstream ifs(cfile.c_str());
    try {
      obj.fill(ifs);
    } catch (...) {
      myerror += "\nunable to create JSON object from '" + cfile + "'";
      return false;
    }
    ifs.close();
    if (!obj) {
      myerror += "\nError reading CrossRef author JSON for works DOI '" +
          subj_doi + "': 'unable to create JSON object'";
      stringstream oss, ess;
      mysystem2("/bin/tcsh -c \"/bin/rm -f " + cfile + "\"", oss, ess);
      return false;
    }
    auto authlst = obj["message"]["author"];
    for (size_t m = 0; m < authlst.size(); ++m) {
      auto family = substitute(authlst[m]["family"].to_string(), "\\", "\\\\");
      auto given = authlst[m]["given"].to_string();
      string fname, mname;
      if (!given.empty()) {
        auto sp = split(given);
        fname = substitute(sp.front(), "\\", "\\\\");
        if (sp.size() > 1) {
          mname = substitute(sp.back(), "\\", "\\\\");
        }
        auto orcid = authlst[m]["ORCID"].to_string();
        if (orcid.empty()) {
          orcid = "NULL";
        } else {
          if (orcid.find("http") == 0) {
            auto idx = orcid.rfind("/");
            if (idx != string::npos) {
              orcid = orcid.substr(idx + 1);
            }
          }
          orcid = "'" + orcid + "'";
        }
        if (g_server.insert("citation.works_authors", "id, id_type, last_name, "
            "first_name, middle_name, orcid_id, sequence", "'" + subj_doi +
            "', 'DOI', '" + sql_ready(family) + "', '" + sql_ready(fname) +
            "', '" + sql_ready( mname) + "', " + orcid + ", " + to_string(m),
            "update id_type = values(id_type), orcid_id = if(isnull(values("
            "orcid_id)), orcid_id, values(orcid_id)), sequence = values("
            "sequence)") < 0) {
          append(myerror, "Error while inserting CrossRef author (" + subj_doi +
              ", DOI, " + family + ", " + fname + ", " + mname + "): '" +
              g_server.error() + "'", "\n");
          stringstream oss, ess;
          mysystem2("/bin/tcsh -c \"/bin/rm -f " + cfile + "\"", oss, ess);
          return false;
        }
      }
    }
  }
  return true;
}

bool filled_authors_from_scopus(string scopus_url, string api_key, string
    subj_doi, JSON::Object& author_obj) {
  auto sp = split(scopus_url, "/");
  auto scopus_id = sp.back();
  auto authfil = g_config_data.tmpdir + "/cache/scopus_id_" + scopus_id +
      ".elsevier.json";
  auto url = scopus_url + "?field=author,dc:publisher&httpAccept=application/"
      "json&apiKey=" + api_key;
  struct stat buf;
  if (stat(authfil.c_str(), &buf) != 0) {
    sleep_for(seconds(1));
    stringstream oss, ess;
    mysystem2("/bin/tcsh -c \"curl -s -o " + authfil + " '" + url + "'\"", oss,
        ess);
    if (!ess.str().empty()) {
      myerror += "\nError while getting Elsevier author data for scopus ID '" +
          scopus_id + "': '" + ess.str() + "'";
      return false;
    }
  }
  std::ifstream ifs(authfil.c_str());
  try {
    author_obj.fill(ifs);
  } catch(...) {
    myerror += "\nunable to create JSON object from '" + authfil + "'";
    return false;
  }
  ifs.close();
  if (!author_obj) {
    myerror += "\nError reading Elsevier JSON for scopus id '" + scopus_id +
        "': 'unable to create JSON object'\n/bin/tcsh -c \"curl -o " + authfil +
        " '" + url + "'\"";
    return false;
  }
  if (author_obj["abstracts-retrieval-response"]["authors"]["author"].size() >
      0) {
    for (size_t m = 0;  m < author_obj["abstracts-retrieval-response"][
        "authors"]["author"].size(); ++m) {
      auto given_name = author_obj["abstracts-retrieval-response"]["authors"][
          "author"][m]["ce:given-name"].to_string();
      if (given_name.empty()) {
        given_name = author_obj["abstracts-retrieval-response"]["authors"][
            "author"][m]["preferred-name"]["ce:given-name"].to_string();
      }
      string fnam, mnam;
      if (!given_name.empty()) {
        auto sp = split(given_name);
        fnam = sp.front();
        sp.pop_front();
        for (const auto& i : sp) {
          if (!mnam.empty()) {
            mnam += " ";
          }
          mnam += i;
        }
      }
      auto seq = author_obj["abstracts-retrieval-response"]["authors"][
          "author"][m]["@seq"].to_string();
      auto lnam = author_obj["abstracts-retrieval-response"]["authors"][
          "author"][m]["ce:surname"].to_string();
      if (g_server.insert("citation.works_authors", "id, id_type, last_name, "
          "first_name, middle_name, sequence", "'" + subj_doi + "', 'DOI', '" +
          sql_ready(lnam) + "', '" + sql_ready(fnam) + "', '" + sql_ready(mnam)
          + "', " + seq, "update id_type = values(id_type), sequence = values("
          "sequence)") < 0) {
        append(myerror, "Error while inserting Scopus author (" + subj_doi +
            ", DOI, " + lnam + ", " + fnam + ", " + mnam + ", " + seq + "): '" +
            g_server.error() + "'", "\n");
        return false;
      }
    }
    return true;
  }
  return false;
}

void regenerate_dataset_descriptions(string whence) {
  LocalQuery q("select v.dsid, count(c.new_flag) from citation.data_citations "
      "as c left join (select distinct dsid, doi from dssdb.dsvrsn) as v on v."
      "doi = c.doi_data where c.new_flag = '1' group by v.dsid");
  if (q.submit(g_server) < 0) {
    myerror += "\nError while obtaining list of new " + whence + " citations: '"
        + q.error() + "'";
    return;
  }
  for (const auto& r : q) {
    g_output << "\nFound " << r[1] << " new " << whence << " data citations "
        "for " << r[0] << endl;
    g_mail_message << "\nFound " << r[1] << " new " << whence << " data "
        "citations for " << r[0] << endl;
    stringstream oss, ess;
    mysystem2("/bin/tcsh -c \"dsgen " + r[0].substr(2) + "\"", oss, ess);
    if (!ess.str().empty()) {
      myerror += "\nError while regenerating " + r[0] + " (" + whence + "):\n  "
          + ess.str();
    }
  }
}

void reset_new_flag() {
  if (g_server.command("update " + g_args.doi_group.db_data.insert_table +
      " set new_flag = '0' where new_flag = '1'") < 0) {
    myerror += "\nError updating 'new_flag' in " + g_args.doi_group.db_data.
        insert_table + ": " + g_server.error();
    return;
  }
}

size_t try_crossref(const DOI_DATA& doi_data, const SERVICE_DATA& service_data,
    string& try_error) {
  static const string API_URL = get<2>(service_data);
  string doi, publisher, asset_type;
  tie(doi, publisher, asset_type) = doi_data;
  size_t ntries = 0;
  while (ntries < 3) {
    sleep_for(seconds(ntries * 5));
    ++ntries;
    auto filename = doi;
    replace_all(filename, "/", "@@");
    filename = g_config_data.tmpdir + "/" + filename + ".crossref.json";
    string url = API_URL + "?source=crossref&obj-id=" + doi;
    JSON::Object doi_obj;
    get_citations(url, get<0>(service_data), 3, filename, doi_obj);
    if (!doi_obj) {
      try_error += "\nServer response was not a JSON object\n/bin/tcsh -c \""
          "curl -o " + filename + " '" + API_URL + "?source=crossref&obj-id=" +
          doi + "'\"";
      stringstream oss, ess;
      mysystem2("/bin/tcsh -c \"/bin/rm -f " + filename + "\"", oss, ess);
      continue;
    }
    if (doi_obj["status"].to_string() != "ok") {
      try_error += "\nServer failure: '" + doi_obj["message"].to_string() +
          "'\n/bin/tcsh -c \"curl -o " + filename + " '" + API_URL + "?source="
          "crossref&obj-id=" + doi + "'\"";
      stringstream oss, ess;
      mysystem2("/bin/tcsh -c \"/bin/rm -f " + filename + "\"", oss, ess);
      continue;
    }
    for (size_t n = 0; n < doi_obj["message"]["events"].size(); ++n) {

      // get the "works" DOI
      auto sid = doi_obj["message"]["events"][n]["subj_id"].to_string();
      replace_all(sid, "\\/", "/");
      auto sp = split(sid, "doi.org/");
      auto sdoi = sp.back();
      if (g_server.insert(g_args.doi_group.db_data.insert_table, "doi_data, "
          "doi_work, new_flag", "'" + doi + "', '" + sdoi + "', '1'", "update "
          "doi_data = values(doi_data)") < 0) {
        append(myerror, "Error while inserting CrossRef DOIs (" + doi + ", " +
            sdoi + "): '" + g_server.error() + "'", "\n");
        continue;
      }
      if (g_server.insert("citation.sources", "doi_work, doi_data, source", "'"
          + sdoi + "', '" + doi + "', '" + get<0>(service_data) + "'", "update "
          "source = source") < 0) {
        append(myerror, "Error updating CrossRef source for '" + sdoi + "', '" +
            doi + "'", "\n");
      }
      if (g_server.insert("citation.doi_data", "doi_data, publisher, "
          "asset_type", "'" + doi + "', '" + sql_ready(publisher) + "', '" +
          asset_type + "'", "update publisher = values(publisher), asset_type "
          "= values(asset_type)") < 0) {
        append(myerror, "Error updating CrossRef DOI data (" + doi + ", " +
            publisher + ", " + asset_type + "): '" + g_server.error() + "'",
            "\n");
        continue;
      }
      if (g_args.no_works) {
        continue;
      }

      // add the author data for the citing "work"
      JSON::Object sdoi_obj;
      if (!filled_authors_from_cross_ref(sdoi, sdoi_obj)) {
        continue;
      }

      // get the type of the "work" and add type-specific data
      auto typ = sdoi_obj["message"]["type"].to_string();
      if (typ == "journal-article") {
        typ = "J";
        auto pubnam = substitute(sdoi_obj["message"]["container-title"][0]
            .to_string(), "\\", "\\\\");
        if (pubnam.empty()) {
          pubnam = substitute(sdoi_obj["message"]["short-container-title"][0]
            .to_string(), "\\", "\\\\");
        }
        auto& e = sdoi_obj["message"];
        auto vol = e["volume"].to_string();
        auto iss = e["issue"].to_string();
        if (!iss.empty()) {
            vol += "(" + iss + ")";
        }
        if (g_server.insert("citation.journal_works",
                          "doi, pub_name, volume, pages",
                          "'" + sdoi + "', '" + sql_ready(pubnam) + "', '" +
            vol + "', '" + e["page"].to_string() + "'",
                          "update pub_name = values(pub_name), volume = values("
            "volume), pages = values(pages)") < 0) {
          myerror += "\nError while inserting CrossRef journal data (" + sdoi +
              "," + pubnam + "," + sdoi_obj["message"]["volume"].to_string() +
              "," + sdoi_obj["message"]["page"].to_string() + "): '" + g_server.
              error() + "'";
        }
      } else if (typ == "book-chapter") {
        typ = "C";
        auto isbn = sdoi_obj["message"]["ISBN"][0].to_string();
        if (isbn.empty()) {
          myerror += "\nError obtaining CrossRef ISBN for book chapter (DOI: " +
              sdoi + ")";
          continue;
        }
        if (g_server.insert("citation.book_chapter_works", ("doi, pages, isbn"),
            ("'" + sdoi + "', '" + sdoi_obj["message"]["page"].to_string() +
            "', '" + isbn + "'"), "update pages = values(pages), isbn = values("
            "isbn)") < 0) {
          myerror += "\nError while inserting book chapter data (" + sdoi + ","
              + sdoi_obj["message"]["pages"].to_string() + "," + isbn + "): '" +
              g_server.error() + "'";
          continue;
        }
        if (!inserted_book_data(isbn)) {
          myerror += "\nError inserting ISBN '" + isbn + "' from CrossRef";
          continue;
        }
      } else if (typ == "proceedings-article" || (typ == "posted-content" &&
          sdoi_obj["message"]["subtype"].to_string() == "preprint")) {
        typ = "P";
        auto pubnam = substitute(sdoi_obj["message"]["container-title"][0]
            .to_string(), "\\", "\\\\");
        if (pubnam.empty()) {
          pubnam = substitute(sdoi_obj["message"]["short-container-title"][0]
            .to_string(), "\\", "\\\\");
        }
        if (g_server.insert("citation.proceedings_works",
                          "doi, pub_name, volume, pages",
                          "'" + sdoi + "', '" + sql_ready(pubnam) + "', '', "
            "''",
                          "update pub_name = values(pub_name)") < 0) {
          myerror += "\nError while inserting CrossRef proceedings data (" +
              sdoi + ", " + pubnam + ", '', ''): '" + g_server.error() + "'";
          continue;
        }
      } else {
        myerror += "\n**UNKNOWN CrossRef TYPE: " + typ + " for work DOI: '" +
            sdoi + "' citing '" + doi + "'";
        continue;
      }

      // add general data about the "work"
      auto pubyr = sdoi_obj["message"]["published-print"]["date-parts"][0][0].
          to_string();
      if (pubyr.empty()) {
        if (typ == "P") {
          pubyr = sdoi_obj["message"]["issued"]["date-parts"][0][0].to_string();
          auto sp = split(pubyr, ",");
          pubyr = sp.front();
        } else {
          pubyr = sdoi_obj["message"]["published-online"]["date-parts"][0][0].
              to_string();
        }
      }
      auto ttl = repair_string(sdoi_obj["message"]["title"][0].to_string());
      auto publisher = sdoi_obj["message"]["publisher"].to_string();
      if (g_server.insert("citation.works", "doi, title, pub_year, type, "
          "publisher", "'" + sdoi + "', '" + sql_ready(ttl) + "', '" + pubyr +
          "', '" + typ + "', '" + sql_ready(publisher) + "'", "update title = "
          "values(title), pub_year = values(pub_year), type = values(type), "
          "publisher = values(publisher)") < 0) {
        myerror += "\nError while CrossRef inserting work (" + sdoi + "," + ttl
            + "," + pubyr + "," + typ + "," + publisher + "): '" + g_server.
            error() + "'";
        continue;
      }
    }
    try_error = "";
    break;
  }
  return ntries;
}

void query_crossref(const DOI_LIST& doi_list, const SERVICE_DATA&
    service_data) {
  string doi, publisher, asset_type;
  for (const auto& e : doi_list) {
    tie(doi, publisher, asset_type) = e;
    g_output << "    querying DOI '" << doi << " | " << publisher << " | " <<
        asset_type << "' ..." << endl;
    string try_error;
    auto ntries = try_crossref(e, service_data, try_error);
    if (ntries == 3) {
      append(myerror, "Error reading CrossRef JSON for DOI '" + doi + "': '" +
          try_error + "'\n/bin/tcsh -c \"curl '" + get<2>(service_data) +
          "?source=crossref&obj-id=" + doi + "'\"", "\n");
    }
  }
  if (g_args.doi_group.id == "rda") {
    regenerate_dataset_descriptions(get<0>(service_data));
  }
  reset_new_flag();
}

string publisher_from_cross_ref(string subj_doi) {
  auto filename = cache_file(subj_doi);
  if (!filename.empty()) {
    ifstream ifs(filename.c_str());
    JSON::Object obj;
    try {
      obj.fill(ifs);
    } catch (...) {
      myerror += "\nunable to create JSON object from '" + filename + "'";
      return "";
    }
    if (!obj) {
      myerror += "\nError reading CrossRef publisher JSON for works DOI '" +
          subj_doi + "': 'unable to create JSON object'";
      stringstream oss, ess;
      mysystem2("/bin/tcsh -c \"/bin/rm -f " + filename + "\"", oss, ess);
      return "";
    }
    return obj["message"]["publisher"].to_string();
  }
  return "";
}

void query_elsevier(const DOI_LIST& doi_list, const SERVICE_DATA&
    service_data) {
  string doi, publisher, asset_type;
  for (const auto& e : doi_list) {
    tie(doi, publisher, asset_type) = e;
    g_output << "    querying DOI '" << doi << " | " << publisher << " | " <<
        asset_type << "' ..." << endl;
    auto pgnum = 0;
    auto totres = 0x7fffffff;
    while (pgnum < totres) {
      auto filename = doi;
      replace_all(filename, "/", "@@");
      filename = g_config_data.tmpdir + "/" + filename + ".elsevier." +
          to_string(pgnum) + ".json";
      string url = get<2>(service_data) + "?start=" + to_string(pgnum) +
          "&query=ALL:" + doi + "&field=prism:doi,prism:url,prism:"
          "publicationName,prism:coverDate,prism:volume,prism:pageRange,prism:"
          "aggregationType,prism:isbn,dc:title&httpAccept=application/json&"
          "apiKey=" + get<3>(service_data);
      JSON::Object doi_obj;
      size_t num_tries = 0;
      for (; num_tries < 3; ++num_tries) {
        sleep_for(seconds(num_tries * 5));
        get_citations(url, get<0>(service_data), 1, filename, doi_obj);
        if (doi_obj && doi_obj["service-error"].type() == JSON::ValueType::
            Nonexistent) {
          break;
        } else {
          stringstream oss, ess;
          mysystem2("/bin/tcsh -c \"/bin/rm -f " + filename + "\"", oss, ess);
        }
      }
      if (num_tries == 3) {
        myerror += "\nError reading Elsevier JSON for DOI '" + doi + "': '"
            "unable to create JSON object'\n/bin/tcsh -c \"curl -o " + filename
            + " '" + url + "'\"";
        continue;
      }
      try {
        totres = stoi(doi_obj["search-results"]["opensearch:totalResults"].
            to_string());
      } catch (const std::invalid_argument& e) {
        myerror += "\ninvalid JSON for '" + url + "'";
        continue;
      } catch (...) {
        myerror += "\nunknown error in JSON for '" + url + "'";
        continue;
      }
      pgnum += stoi(doi_obj["search-results"]["opensearch:itemsPerPage"].
          to_string());
      if (totres == 0) {
        continue;
      }
      for (size_t n = 0; n < doi_obj["search-results"]["entry"].size(); ++n) {

        // get the "works" DOI
        if (doi_obj["search-results"]["entry"][n]["prism:doi"].type() == JSON::
            ValueType::Nonexistent) {
          myerror += "\n**NO Elsevier WORKS DOI:  Data DOI - " + doi +
              "  type - " + doi_obj["search-results"]["entry"][n][
              "prism:aggregationType"].to_string() + "  title - '" + doi_obj[
              "search-results"]["entry"][n]["dc:title"].to_string() + "'";
          continue;
        }
        auto sdoi = doi_obj["search-results"]["entry"][n]["prism:doi"].
            to_string();
        replace_all(sdoi, "\\/","/");
        if (g_server.insert(g_args.doi_group.db_data.insert_table, "doi_data, "
            "doi_work, new_flag", "'" + doi + "', '" + sdoi + "', '1'",
            "update doi_data = values(doi_data)") < 0) {
          append(myerror, "Error while inserting Elsevier DOIs (" + doi + ", " +
              sdoi + "): '" + g_server.error() + "'", "\n");
          continue;
        }
        if (g_server.insert("citation.sources", "doi_work, doi_data, source",
            "'" + sdoi + "', '" + doi + "', '" + get<0>(service_data) + "'",
            "update source = source") < 0) {
          append(myerror, "Error updating Scopus source for '" + sdoi + "', '" +
              doi + "'", "\n");
        }
        if (g_server.insert("citation.doi_data", "doi_data, publisher, "
            "asset_type", "'" + doi + "', '" + sql_ready(publisher) + "', '" +
            asset_type + "'", "update publisher = values(publisher), "
            "asset_type = values(asset_type)") < 0) {
          append(myerror, "Error updating Elsevier DOI data (" + doi + ", " +
              publisher + ", " + asset_type + "): '" + g_server.error() + "'",
              "\n");
          continue;
        }
        if (g_args.no_works) {
          continue;
        }

        // add the author data for the citing "work"
        auto prism_url = doi_obj["search-results"]["entry"][n]["prism:url"];
        if (prism_url.type() == JSON::ValueType::Nonexistent) {
          myerror += "\n**NO Elsevier SCOPUS ID: " + filename + " " + prism_url.
              to_string();
          continue;
        }
        auto scopus_url = prism_url.to_string();
        JSON::Object author_obj;
        if (!filled_authors_from_scopus(scopus_url, get<3>(service_data), sdoi,
            author_obj)) {
          JSON::Object cr_obj;
          filled_authors_from_cross_ref(sdoi, cr_obj);
        }

        // get the type of the "work" and add type-specific data
        auto typ = doi_obj["search-results"]["entry"][n][
            "prism:aggregationType"].to_string();
        if (typ == "Journal") {
          typ = "J";
          auto pubnam = doi_obj["search-results"]["entry"][n][
              "prism:publicationName"].to_string();
          if (g_server.insert("citation.journal_works", "doi, pub_name, "
              "volume, pages", "'" + sdoi + "', '" + sql_ready(pubnam) + "', '"
              + doi_obj["search-results"]["entry"][n]["prism:volume"].
              to_string() + "', '" + doi_obj["search-results"]["entry"][n][
              "prism:pageRange"].to_string() + "'", "update pub_name = values("
              "pub_name), volume = values(volume), pages = values(pages)") <
              0) {
            append(myerror, "Error while inserting Elsevier journal data ('" +
                sdoi + "', '" + sql_ready(pubnam) + "', '" + doi_obj[
                "search-results"]["entry"][n]["prism:volume"].to_string() +
                "', '" + doi_obj["search-results"]["entry"][n][
                "prism:pageRange"].to_string() + "'): '" + g_server.error() +
                "'", "\n");
            continue;
          }
        } else if (typ == "Book" || typ == "Book Series") {
          typ = "C";
          auto isbn = doi_obj["search-results"]["entry"][n]["prism:isbn"][0][
              "$"].to_string();
          if (isbn.empty()) {
            myerror += "\nError obtaining Elsevier ISBN for book chapter (DOI: "
                + sdoi + ")";
            continue;
          }
          if (g_server.insert("citation.book_chapter_works", ("doi, pages, "
              "isbn"), ("'" + sdoi + "', '" + doi_obj["search-results"][
              "entry"][n]["prism:pageRange"].to_string() + "', '" + isbn + "'"),
              "update pages = values(pages), isbn = values(isbn)") < 0) {
            myerror += "\nError while inserting book chapter data (" + sdoi +
                ", " + doi_obj["search-results"]["entry"][n]["prism:pageRange"].
                to_string() + ", " + isbn + "): '" + g_server.error() + "'";
            continue;
          }
          if (!inserted_book_data(isbn)) {
            myerror += "\nError inserting ISBN '" + isbn + "' from Elsevier";
            continue;
          }
        } else if (typ == "Conference Proceeding") {
          typ = "P";
          auto& e = doi_obj["search-results"]["entry"][n];
          if (g_server.insert("citation.proceedings_works",
                            "doi, pub_name, volume, pages",
                            "'" + sdoi + "', '" + e["prism:publicationName"].
              to_string() + "', '" + e["prism:volume"].to_string() + "', '" +e[
              "prism:pageRange"].to_string() + "'",
                            "update pub_name = values(pub_name), volume = "
              "values(volume), pages = values(pages)") < 0) {
            myerror += "\nError while inserting Elsevier proceedings data (" +
                sdoi + ", " + doi_obj["search-results"]["entry"][n][
                "prism:publicationName"].to_string() + ", " + doi_obj[
                "search-results"]["entry"][n]["prism:pageRange"].to_string() +
                "): '" + g_server.error() + "'";
            continue;
          }
        } else {
          myerror += "\n**UNKNOWN Elsevier TYPE: " + typ + " for work DOI: '" +
              sdoi + "' citing '" + doi + "'";
          continue;
        }

        // add general data about the "work"
        auto pubyr = doi_obj["search-results"]["entry"][n]["prism:coverDate"].
            to_string().substr(0, 4);
        if (!pubyr.empty()) {
          auto ttl = repair_string(doi_obj["search-results"]["entry"][n][
              "dc:title"].to_string());
          auto publisher = author_obj["abstracts-retrieval-response"][
              "coredata"]["dc:publisher"].to_string();
          if (publisher.empty()) {
            publisher = publisher_from_cross_ref(sdoi);
          }
          if (g_publisher_fixups.find(publisher) != g_publisher_fixups.end()) {
            publisher = g_publisher_fixups[publisher];
          } else {
            if (regex_search(publisher, email_re)) {
              if (g_publisher_fixups.find(publisher) == g_publisher_fixups.
                  end()) {
                myerror += "\n**SUSPECT PUBLISHER: '" + publisher + "'";
              } else {
                publisher = g_publisher_fixups[publisher];
              }
            }
          }
          if (g_server.insert("citation.works", "doi, title, pub_year, type, "
              "publisher", "'" + sdoi + "', '" + sql_ready(ttl) + "', '" +
              pubyr + "', '" + typ + "', '" + sql_ready(publisher) + "'",
              "update title = values(title), pub_year = values(pub_year), type "
              "= values(type), publisher = values(publisher)") < 0) {
            myerror += "\nError while Elsevier inserting work (" + sdoi + ", " +
                ttl + ", " + pubyr + ", " + typ + ", " + publisher + ") from "
                "file '" + filename + "': '" + g_server.error() + "'";
            continue;
          }
        } else {
          myerror += "\n**NO Elsevier PUBLICATION YEAR: SCOPUS URL - " +
              scopus_url;
        }
      }
    }
  }
  if (g_args.doi_group.id == "rda") {
    regenerate_dataset_descriptions(get<0>(service_data));
  }
  reset_new_flag();
}

tuple<string, string> parse_author_first_name(string fname) {
  tuple<string, string> t; // return value
  if (!fname.empty()) {
    auto sp = split(fname);
    get<0>(t) = sp.front();
    sp.pop_front();
    for (const auto& e : sp) {
      append(get<1>(t), e, " ");
    }
  }
  return std::move(t);
}

void fill_authors_from_wos(string doi_work, const JSON::Value& v) {
  vector<tuple<string, string, string, string, size_t>> author_names;
  if (v.type() == JSON::ValueType::Array) {
    for (size_t n = 0; n < v.size(); ++n) {
      auto& names = v[n]["names"]["name"];
      if (names.type() == JSON::ValueType::Array) {
        for (size_t m = 0; m < names.size(); ++m) {
          string fname, mname;
          tie(fname, mname) = parse_author_first_name(names[m]["first_name"].
              to_string());
          author_names.emplace_back(make_tuple(fname, mname, names[m][
              "last_name"].to_string(), names[m]["orcid_id"].to_string(), stoi(
              names[m]["seq_no"].to_string()) - 1));
        }
      } else {
        string fname, mname;
        tie(fname, mname) = parse_author_first_name(names["first_name"].
            to_string());
        author_names.emplace_back(make_tuple(fname, mname, names["last_name"].
            to_string(), names["orcid_id"].to_string(), stoi(names["seq_no"].
            to_string()) - 1));
      }
    }
  } else {
    auto& names = v["names"]["name"];
    if (names.type() == JSON::ValueType::Array) {
      for (size_t m = 0; m < names.size(); ++m) {
        string fname, mname;
        tie(fname, mname) = parse_author_first_name(names[m]["first_name"].
            to_string());
        author_names.emplace_back(make_tuple(fname, mname, names[m][
            "last_name"].to_string(), names[m]["orcid_id"].to_string(), stoi(
            names[m]["seq_no"].to_string()) - 1));
      }
    } else {
      string fname, mname;
      tie(fname, mname) = parse_author_first_name(names["first_name"].
          to_string());
      author_names.emplace_back(make_tuple(fname, mname, names["last_name"].
          to_string(), names["orcid_id"].to_string(), stoi(names["seq_no"].
          to_string()) - 1));
    }
  }
  for (const auto& name : author_names) {
    if (g_server.insert("citation.works_authors", "id, id_type, last_name, "
        "first_name, middle_name, orcid_id, sequence", "'" + doi_work + "', "
        "'DOI', '" + sql_ready(get<2>(name)) + "', '" + sql_ready(get<0>(name))
        + "', '" + sql_ready(get<1>(name)) + "', '" + get<3>(name) + "', " +
        to_string(get<4>(name)), "update id_type = values(id_type), sequence = "
        "values(sequence)") < 0) {
      append(myerror, "Error while inserting WoS author (DOI " + doi_work +
          ", '" + get<2>(name) + "', '" + get<0>(name) + "', '" + get<1>(name) +
          "', '" + get<3>(name) + "', " + to_string(get<4>(name)) + "): '" +
          g_server.error() + "'", "\n");
    }
  }
}

void query_wos(const DOI_LIST& doi_list, const SERVICE_DATA& service_data) {
//return;
  static const string API_URL = get<2>(service_data);
  static const string API_KEY_HEADER = "X-ApiKey: " + get<3>(service_data);
  string doi, publisher, asset_type;
  for (const auto& e : doi_list) {
    tie(doi, publisher, asset_type) = e;
if (to_lower(doi) == "10.5065/8a4y-cg39") {
continue;
}
    g_output << "    querying DOI '" << doi << " | " << publisher << " | " <<
        asset_type << "' ..." << endl;

    // get the WoS ID for the DOI
    stringstream oss, ess;
    if (mysystem2("/bin/tcsh -c \"curl -H '" + API_KEY_HEADER + "' '" + API_URL
        + "/?databaseId=WOK&usrQuery=DO=" + doi + "&count=1&firstRecord=1&"
        "viewField=none'\"", oss, ess) < 0) {
      append(myerror, "Error getting WoS ID for DOI '" + doi + "'", "\n");
      continue;
    }
    JSON::Object o(oss.str());
    if (!o) {
      append(myerror, "Wos response for DOI '" + doi + "' ID is not JSON",
          "\n");
      continue;
    }
    auto wos_id = o["Data"]["Records"]["records"]["REC"][0]["UID"].to_string();
    if (wos_id.empty()) {
      g_output << "      No WoS ID found" << endl;
      continue;
    }
    g_output << "      WoS ID: '" << wos_id << "'" << endl;

    // get the WoS IDs for the "works" that have cited this DOI
    vector<string> works_ids;
    auto count = 100;
    auto first_rec = 1;
    auto num_records = 2;
    while (first_rec < num_records) {
      if (mysystem2("/bin/tcsh -c \"curl -H '" + API_KEY_HEADER + "' '" +
          API_URL + "/citing?databaseId=WOS&uniqueId=" + wos_id + "&count=" +
          to_string(count) + "&firstRecord=" + to_string(first_rec) +
          "&viewField='\"", oss, ess) < 0) {
        append(myerror, "Error getting WoS citation IDs for DOI '" + doi + "'",
            "\n");
        continue;
      }
      o.fill(oss.str());
      auto& arr = o["Data"]["Records"]["records"]["REC"];
      if (arr.type() != JSON::ValueType::Nonexistent) {
        for (size_t n = 0; n < arr.size(); ++n) {
          works_ids.emplace_back(arr[n]["UID"].to_string());
        }
        num_records = stoi(o["QueryResult"]["RecordsFound"].to_string());
      }
      first_rec += count;
    }
    g_output << "      " << works_ids.size() << " citations found ..." <<
        endl;
    for (const auto& work_id : works_ids) {
      string view_field = "identifiers";
      if (!g_args.no_works) {
        view_field += "+names+titles+pub_info";
      }

      // get the data for each "work"
      auto cache_fn = g_config_data.tmpdir + "/cache/" + work_id + ".json";
      struct stat buf;
      if (stat(cache_fn.c_str(), &buf) != 0) {
        if (mysystem2("/bin/tcsh -c \"curl -H '" + API_KEY_HEADER + "' -s -o " +
            cache_fn + " '" + API_URL + "/id/" + work_id + "?databaseId=WOS&"
            "count=1&firstRecord=1&viewField=" + view_field + "'\"", oss, ess) <
            0) {
          append(myerror, "Error get WoS work data for ID '" + work_id + "' "
              "(DOI " + doi + ")", "\n");
          continue;
        }
      }
      ifstream ifs(cache_fn.c_str());
      o.fill(ifs);
      if (!o) {
        append(myerror, "Error - '" + cache_fn + "' is not a JSON file (DOI " +
            doi + ")", "\n");
        continue;
      }
      auto& record = o["Data"]["Records"]["records"]["REC"][0];
      auto& identifiers = record["dynamic_data"]["cluster_related"][
          "identifiers"]["identifier"];
      string doi_work;
      for (size_t n = 0; n < identifiers.size(); ++n) {
        if (identifiers[n]["type"].to_string() == "doi") {
          doi_work = identifiers[n]["value"].to_string();
          break;
        }
      }
      if (doi_work.empty()) {
        append(myerror, "Missing work DOI for WoS ID '" + work_id + "' (DOI " +
            doi + ")", "\n");
        continue;
      }
      g_output << "        WoS ID: '" << work_id << "', DOI: '" << doi_work <<
          "'" << endl;
      if (g_server.insert(g_args.doi_group.db_data.insert_table, "doi_data, "
          "doi_work, new_flag", "'" + doi + "', '" + doi_work + "', '1'",
            "update doi_data = values(doi_data)") < 0) {
        append(myerror, "Error while inserting WoS DOIs (" + doi + ", " +
            doi_work + "): '" + g_server.error() + "'", "\n");
        continue;
      }
      if (g_server.insert("citation.sources", "doi_work, doi_data, source", "'"
          + doi_work + "', '" + doi + "', '" + get<0>(service_data) + "'",
          "update source = source") < 0) {
        append(myerror, "Error updating WoS source for '" + doi_work + "', '" +
            doi + "'", "\n");
      }
      if (g_server.insert("citation.doi_data", "doi_data, publisher, "
          "asset_type", "'" + doi + "', '" + sql_ready(publisher) + "', '" +
          asset_type + "'", "update publisher = values(publisher), asset_type "
          "= values(asset_type)") < 0) {
        append(myerror, "Error updating Elsevier DOI data (" + doi + ", " +
            publisher + ", " + asset_type + "): '" + g_server.error() + "'",
            "\n");
        continue;
      }
      if (g_args.no_works) {
        continue;
      }

      // add author data for the citing "work"
      auto& address_names = record["static_data"]["fullrecord_metadata"][
          "addresses"]["address_name"];
      fill_authors_from_wos(doi_work, address_names);

      // get the type of the "work" and add type-specific data
      auto& summary = record["static_data"]["summary"];
      auto& pub_info = summary["pub_info"];
      auto pubtype = pub_info["pubtype"].to_string();
      string item_title;
      if (pubtype == "Journal") {
        pubtype = "J";
        auto& titles = summary["titles"]["title"];
        string pubnam;
        for (size_t n = 0; n < titles.size(); ++n) {
          auto type = titles[n]["type"].to_string();
          if (type == "source") {
            pubnam = to_title(titles[n]["content"].to_string());
          } else if (type == "item") {
            item_title = titles[n]["content"].to_string();
          }
        }
        if (pubnam.empty()) {
          append(myerror, "Unable to find WoS publication name (" + work_id +
              ")", "\n");
          continue;
        }
        auto vol = pub_info["vol"].to_string();
        auto issue = pub_info["issue"].to_string();
        if (!issue.empty()) {
          vol += "(" + issue + ")";
        }
        if (g_server.insert("citation.journal_works",
                          "doi, pub_name, volume, pages",
                          "'" + doi_work + "', '" + sql_ready(pubnam) + "', '" +
            vol + "', '" + pub_info["page"]["content"].to_string() + "'",
                          "update pub_name = values(pub_name), volume = values("
            "volume), pages = values(pages)") < 0) {
          append(myerror, "Error while inserting WoS journal data ('" + doi_work
              + "', '" + sql_ready(pubnam) + "', '" + vol + "', '" + pub_info[
              "page"]["content"].to_string() + "'): '" + g_server.error() + "'",
              "\n");
          continue;
        }
      } else {
        append(myerror, "Unknown WoS pubtype '" + pubtype + "' (" + work_id +
            ")", "\n");
        continue;
      }
      if (item_title.empty()) {
        append(myerror, "Unable to find WoS item title (" + work_id + ")",
            "\n");
        continue;
      }

      // add general data about the "work"
      auto pubyr = pub_info["pubyear"].to_string();
      if (!pubyr.empty()) {
        auto& p = summary["publishers"]["publisher"]["names"]["name"];
        auto publisher = p["unified_name"].to_string();
        if (publisher.empty()) {
          publisher = to_title(p["full_name"].to_string());
        }
        if (publisher.empty()) {
          append(myerror, "**NO WoS PUBLISHER (" + work_id + ")", "\n");
          continue;
        }
        if (g_server.insert("citation.works", "doi, title, pub_year, type, "
            "publisher", "'" + doi_work + "', '" + sql_ready(item_title) +
            "', '" + pubyr + "', '" + pubtype + "', '" + sql_ready(publisher) +
            "'", "update title = values(title), pub_year = values(pub_year), "
            "type = values(type), publisher = values(publisher)") < 0) {
          append(myerror, "Error while WoS inserting work (" + doi_work + ", " +
                item_title + ", " + pubyr + ", " + pubtype + ", " + publisher +
                ") from WoS '" + work_id + "': '" + g_server.error() + "'",
                "\n");
            continue;
          }
      } else {
        append(myerror, "**NO WoS PUBLICATION YEAR (" + work_id + ")", "\n");
      }
    }
  }
  if (g_args.doi_group.id == "rda") {
    regenerate_dataset_descriptions(get<0>(service_data));
  }
  reset_new_flag();
}

void assert_configuration_value(string value_name, const JSON::Value& value,
    JSON::ValueType assert_type, string id) {
  if (value.type() != assert_type) {
    add_to_error_and_exit("'" + value_name + "' not found in configuration "
        "file, or is not a string (id=" + id + ")");
  }
}

string url_encode(string url) {
  replace_all(url, "[", "%5B");
  replace_all(url, "]", "%5D");
  return url;
}

void read_config() {
  std::ifstream ifs("/glade/u/home/dattore/dois/citefind.cnf");
  if (!ifs.is_open()) {
    add_to_error_and_exit("unable to open configuration file");
  }
  JSON::Object o(ifs);
  ifs.close();
  assert_configuration_value("temp-dir", o["temp-dir"], JSON::ValueType::String,
      "main");
  g_config_data.tmpdir = o["temp-dir"].to_string();
  assert_configuration_value("default-asset-type", o["default-asset-type"],
      JSON::ValueType::String, "main");
  g_config_data.default_asset_type = o["default-asset-type"].to_string();
  struct stat buf;
  if (stat(g_config_data.tmpdir.c_str(), &buf) != 0) {
    add_to_error_and_exit("temporary directory '" + g_config_data.tmpdir + "' "
        "is missing");
  }
  g_output.open(g_config_data.tmpdir + "/output." + dateutils::
      current_date_time().to_string("%Y%m%d%H%MM"));
  g_output << "Configuration file open and ready to parse ..." << endl;
  auto& doi_groups = o["doi-groups"];
  for (size_t n = 0; n < doi_groups.size(); ++n) {
    auto& a = doi_groups[n];
    g_config_data.doi_groups.emplace_back(ConfigData::DOI_Group());
    auto& c = g_config_data.doi_groups.back();
    assert_configuration_value("id", a["id"], JSON::ValueType::String,
        to_string(n));
    c.id = a["id"].to_string();
    g_output << "    found ID '" << a["id"].to_string() << "'" << endl;
    assert_configuration_value("publisher", a["publisher"], JSON::ValueType::
        String, c.id);
    c.publisher = a["publisher"].to_string();
    assert_configuration_value("db", a["db"], JSON::ValueType::Object, c.id);
    auto& db = a["db"];
    assert_configuration_value("host", db["host"], JSON::ValueType::String, c.
        id);
    c.db_data.host = db["host"].to_string();
    assert_configuration_value("username", db["username"], JSON::ValueType::
        String, c.id);
    c.db_data.username = db["username"].to_string();
    assert_configuration_value("password", db["password"], JSON::ValueType::
        String, c.id);
    c.db_data.password = db["password"].to_string();
    assert_configuration_value("insert-table", db["insert-table"], JSON::
        ValueType::String, c.id);
    c.db_data.insert_table = db["insert-table"].to_string();
    if (db["doi"].type() != JSON::ValueType::Nonexistent) {
      c.db_data.doi_query = db["doi"].to_string();
    }
    if (a["api"].type() != JSON::ValueType::Nonexistent) {
      auto& api = a["api"];
      assert_configuration_value("url", api["url"], JSON::ValueType::String, c.
          id);
      c.api_data.url = api["url"].to_string();
      assert_configuration_value("response:doi", api["response"]["doi"], JSON::
          ValueType::String, c.id);
      c.api_data.response.doi_path = api["response"]["doi"].to_string();
      assert_configuration_value("response:publisher", api["response"][
          "publisher"], JSON::ValueType::String, c.id);
      c.api_data.response.publisher_path = api["response"]["publisher"].
          to_string();
      if (api["response"]["asset-type"].type() == JSON::ValueType::String) {
        c.api_data.response.asset_type_path = api["response"]["asset-type"].
            to_string();
      }
      if (api["pagination"].type() != JSON::ValueType::Nonexistent) {
        auto& paging = api["pagination"];
        assert_configuration_value("pagination:page-count", paging[
            "page-count"], JSON::ValueType::String, c.id);
        c.api_data.pagination.page_cnt = url_encode(paging["page-count"].
            to_string());
        assert_configuration_value("pagination:page-number", paging[
            "page-number"], JSON::ValueType::String, c.id);
        c.api_data.pagination.page_num = url_encode(paging["page-number"].
            to_string());
      }
    }
  }
  auto& services = o["services"];
  for (size_t n = 0; n < services.size(); ++n) {
    auto id = services[n]["id"].to_string();
    if (!id.empty()) {
      g_services.emplace(id, make_tuple(services[n]["name"].to_string(),
          services[n]["title"].to_string(), services[n]["url"].to_string(),
          services[n]["api-key"].to_string(), true));
    }
  }
  g_output << "... configuration file parsed." << endl;
}

void clean_cache() {
  stringstream oss, ess;
  if (mysystem2("/bin/tcsh -c 'find " + g_config_data.tmpdir + "/cache/* "
      "-mtime +180 -exec rm {} \\;'", oss, ess) != 0) {
    add_to_error_and_exit("unable to clean cache - error: '" + ess.str() + "'");
  }
}

void show_usage_and_exit() {
  cerr << "usage: citefind DOI_GROUP [ options... ]" << endl;
  cerr << "usage: citefind --help" << endl;
  cerr << "usage: citefind --show-doi-groups" << endl;
  cerr << "\nrequired:" << endl;
  cerr << "DOI_GROUP  doi group for which to get citation statistics" << endl;
  cerr << "\noptions:" << endl;
  cerr << "  -d DOI_DATA                get citation data for a single DOI "
      "only (don't" << endl;
  cerr << "                               build a list)" << endl;
  cerr << "                             DOI_DATA is a delimited list (see -s) "
      "containing" << endl;
  cerr << "                               three items:" << endl;
  cerr << "                               - the DOI" << endl;
  cerr << "                               - the publisher of the DOI" << endl;
  cerr << "                               - the asset type (e.g. dataset, "
      "software, etc.)" << endl;
  cerr << "  -k                         keep the json files from the APIs ("
      "default is to" << endl;
  cerr << "                               remove them)" << endl;
  cerr << "  --no-works                 don't collect information about citing "
      "works" << endl;
  cerr << "  --only-services SERVICES   comma-delimited list of services to "
      "query (any not" << endl;
  cerr << "                               specified will be ignored)" << endl;
  cerr << "  --no-services SERVICES     comma-delimited list of services to "
      "ignore" << endl;
  cerr << "  -s DELIMITER               delimiter string for DOI_DATA, "
      "otherwise a" << endl;
  cerr << "                               semicolon is the default" << endl;
  g_args.clean_tmpdir = false;
  exit(1);
}

void show_doi_groups_and_exit() {
  cout << "Known doi groups:" << endl;
  for (const auto& c : g_config_data.doi_groups) {
    cout << "  " << c.id << endl;
  }
  cout << "\nAdd additional doi groups to the configuration file" << endl;
  exit(0);
}

void parse_args(int argc, char **argv) {
  string a1;
  if (argc > 1) {
    a1 = argv[1];
  }
  if (argc < 2 || a1 == "--help") {
    show_usage_and_exit();
  }
  if (a1 == "--show-doi-groups") {
    show_doi_groups_and_exit();
  }
  for (const auto& g : g_config_data.doi_groups) {
    if (g.id == a1) {
      g_args.doi_group = g;
      break;
    }
  }
  if (g_args.doi_group.id.empty()) {
    add_to_error_and_exit("doi group '" + a1 + "' is not configured");
  }
  g_output << "Looking for citation statistics for ID '" << g_args.doi_group.id
      << "'." << endl;
  g_output << "Default publisher is '" << g_args.doi_group.publisher << "'." <<
      endl;
  if (!g_args.doi_group.api_data.response.publisher_path.empty()) {
    g_output << "    The path '" << g_args.doi_group.api_data.response.
        publisher_path << "' will override the default, if found." << endl;
  }
  if (g_args.doi_group.api_data.response.asset_type_path.empty()) {
    g_output << "No asset-type path specified, so using the default value '" <<
        g_config_data.default_asset_type << "' for DOIs." << endl;
  } else {
    g_output << "Specified asset-type path '" << g_args.doi_group.api_data.
        response.asset_type_path << "' will be used for DOIs." << endl;
  }
  string doi_data;
  string doi_data_delimiter = ";";
  for (auto n = 2; n < argc; ++n) {
    auto arg = string(argv[n]);
    if (arg == "-d") {
      doi_data = argv[++n];
    } else if (arg == "-k") {
      g_args.clean_tmpdir = false;
    } else if (arg == "--no-works") {
      g_args.no_works = true;
    } else if (arg == "--only-services") {
      auto sp = split(argv[++n], ",");
      for (auto& e : g_services) {
        get<4>(e.second) = false;
      }
      for (const auto& e : sp) {
        if (g_services.find(e) != g_services.end()) {
          get<4>(g_services[e]) = true;
        }
      }
    } else if (arg == "--no-services") {
      auto sp = split(argv[++n], ",");
      for (const auto& e : sp) {
        if (g_services.find(e) != g_services.end()) {
          get<4>(g_services[e]) = false;
        }
      }
    } else if (arg == "-s") {
      doi_data_delimiter = argv[++n];
    }
  }
  if (!doi_data.empty()) {
    auto sp = split(doi_data, doi_data_delimiter);
    if (sp.size() != 3) {
      cerr << "DOI_DATA not specified properly - see usage for details" << endl;
      exit(1);
    }
    g_single_doi = sp[0];
    trim(g_single_doi);
    g_args.doi_group.publisher = sp[1];
    trim(g_args.doi_group.publisher);
    g_config_data.default_asset_type = sp[2];
    trim(g_config_data.default_asset_type);
  }
}

void connect_to_database() {
  g_server.connect("rda-db.ucar.edu", "metadata", "metadata", "rdadb");
  if (!g_server) {
    add_to_error_and_exit("unable to connect to the database");
  }
}

void create_doi_table() {
  if (!table_exists(g_server, g_args.doi_group.db_data.insert_table)) {
    if (g_server.command("create table " + g_args.doi_group.db_data.insert_table
        + " like citation.template_data_citations") < 0) {
      add_to_error_and_exit("unable to create citation table '" + g_args.
          doi_group.db_data.insert_table + "'; error: '" + g_server.error() +
          "'");
    }
  }
}

void fill_journal_abbreviations() {
  LocalQuery q("word, abbreviation", "citation.journal_abbreviations");
  if (q.submit(g_server) < 0) {
    add_to_error_and_exit("unable to get journal abbreviatons: '" + q.error() +
        "'");
  }
  for (const auto& r : q) {
    g_journal_abbreviations.emplace(r[0], r[1]);
  }
}

void fill_journals_no_abbreviation() {
  LocalQuery q("full_name", "citation.journal_no_abbreviation");
  if (q.submit(g_server) < 0) {
    add_to_error_and_exit("unable to get journals with no abbrevations: '" + q.
        error() + "'");
  }
  for (const auto& r : q) {
    g_journals_no_abbreviation.emplace(r[0]);
  }
}

void fill_publisher_fixups() {
  LocalQuery q("original_name, fixup", "citation.publisher_fixups");
  if (q.submit(g_server) < 0) {
    add_to_error_and_exit("unable to get publisher fixups: '" + q.error() +
        "'");
  }
  for (const auto& r : q) {
    g_publisher_fixups.emplace(r[0], r[1]);
  }
}

void fill_doi_list_from_db(DOI_LIST& doi_list) {
  g_output << "    filling list from a database ..." << endl;
  Server srv(g_args.doi_group.db_data.host, g_args.doi_group.db_data.username,
      g_args.doi_group.db_data.password, "rdadb");
  if (!srv) {
    add_to_error_and_exit("unable to connect to MySQL server for the DOI list");
  }
  LocalQuery q(g_args.doi_group.db_data.doi_query);
  if (q.submit(srv) < 0) {
    add_to_error_and_exit("mysql error '" + q.error() + "' while getting the "
        "DOI list");
  }
  doi_list.reserve(q.num_rows());
  for (const auto& r : q) {
    doi_list.emplace_back(make_tuple(r[0], g_args.doi_group.publisher,
        g_config_data.default_asset_type));
  }
  srv.disconnect();
  g_output << "    ... found " << doi_list.size() << " DOIs." << endl;
}

void process_json_value(const JSON::Value& v, deque<string> sp, vector<string>&
    list, string null_value = "") {
  if (v.type() == JSON::ValueType::Array) {
    for (size_t n = 0; n < v.size(); ++n) {
      auto& v2 = v[n];
      process_json_value(v2, sp, list, null_value);
    }
  } else if (v.type() == JSON::ValueType::Object) {
    auto& v2 = v[sp.front()];
    sp.pop_front();
    process_json_value(v2, sp, list, null_value);
  } else if (v.type() == JSON::ValueType::String || v.type() == JSON::
      ValueType::Number) {
    list.emplace_back(v.to_string());
  } else {
    if (v.type() == JSON::ValueType::Null && !null_value.empty()) {
      list.emplace_back(null_value);
    } else {
      add_to_error_and_exit("json value type '" + to_string(static_cast<int>(v.
          type())) + "' not recognized");
    }
  }
}

void fill_doi_list_from_api(DOI_LIST& doi_list) {
  if (g_args.doi_group.api_data.response.doi_path.empty()) {
    add_to_error_and_exit("not configured to handle an API response");
  }
  g_output << "    filling list from an API ..." << endl;
  size_t num_pages = 1;
  size_t page_num = 1;
  for (size_t n = 0; n < num_pages; ++n) {
    auto url = g_args.doi_group.api_data.url;
    if (!g_args.doi_group.api_data.pagination.page_num.empty()) {
      if (url.find("?") == string::npos) {
        url += "?";
      } else {
        url += "&";
      }
      url += g_args.doi_group.api_data.pagination.page_num + "=" + to_string(
          page_num++);
    }
    stringstream oss, ess;
    if (mysystem2("/bin/tcsh -c \"curl -s -o - '" + url + "'\"", oss, ess) !=
        0) {
      add_to_error_and_exit("api error '" + ess.str() + "' while getting the "
          "DOI list");
    }
    JSON::Object o(oss.str());
    auto sp = split(g_args.doi_group.api_data.response.doi_path, ":");
    auto& v = o[sp.front()];
    sp.pop_front();
    vector<string> dlist;
    process_json_value(v, sp, dlist);
    vector<string> alist;
    if (!g_args.doi_group.api_data.response.asset_type_path.empty()) {
      sp = split(g_args.doi_group.api_data.response.asset_type_path, ":");
      auto& v = o[sp.front()];
      sp.pop_front();
      process_json_value(v, sp, alist, g_config_data.default_asset_type);
      if (alist.size() != dlist.size()) {
        add_to_error_and_exit("DOI list size != asset type list size");
      }
    } else {
      alist.insert(alist.begin(), dlist.size(), g_config_data.
          default_asset_type);
    }
    vector<string> plist;
    if (!g_args.doi_group.api_data.response.publisher_path.empty()) {
      sp = split(g_args.doi_group.api_data.response.publisher_path, ":");
      auto& v = o[sp.front()];
      sp.pop_front();
      process_json_value(v, sp, plist, g_args.doi_group.publisher);
      if (plist.size() != dlist.size()) {
        add_to_error_and_exit("DOI list size != publisher list size");
      }
    } else {
      plist.insert(plist.begin(), dlist.size(), g_args.doi_group.publisher);
    }
    for (size_t m = 0; m < dlist.size(); ++m) {
      doi_list.emplace_back(make_tuple(dlist[m], plist[m], to_lower(alist[m])));
    }
    if (num_pages == 1 && !g_args.doi_group.api_data.pagination.page_cnt.
        empty()) {
      auto sp = split(g_args.doi_group.api_data.pagination.page_cnt, ":");
      auto& v = o[sp.front()];
      sp.pop_front();
      vector<string> list;
      process_json_value(v, sp, list);
      num_pages = stoi(list.front());
    }
  }
  g_output << "    ... found " << doi_list.size() << " DOIs." << endl;
}

void fill_doi_list(DOI_LIST& doi_list) {
  g_output << "Filling list of DOIs for '" << g_args.doi_group.id << "' ..." <<
      endl;
  if (!g_single_doi.empty()) {
    doi_list.emplace_back(make_tuple(g_single_doi, g_args.doi_group.publisher,
        g_config_data.default_asset_type));
  } else if (!g_args.doi_group.db_data.doi_query.empty()) {
    fill_doi_list_from_db(doi_list);
  } else if (!g_args.doi_group.api_data.url.empty()) {
    fill_doi_list_from_api(doi_list);
  } else {
    add_to_error_and_exit("can't figure out how to get the list of DOIs from "
        "the current configuration");
  }
  g_output << "... done filling DOI list." << endl;
}

void query_service(string service_id, const SERVICE_DATA& service_data, const
    DOI_LIST& doi_list) {
  g_output << "Querying " << get<0>(service_data) << " ..." << endl;
  if (service_id == "crossref") {
    query_crossref(doi_list, service_data);
  } else if (service_id == "elsevier") {
    query_elsevier(doi_list, service_data);
  } else if (service_id == "wos") {
    query_wos(doi_list, service_data);
  } else {
    append(myerror, "ignoring unknown service '" + service_id + "'", "\n");
  }
  g_output << "... done querying " << get<0>(service_data) << "." << endl;
}

void print_publisher_list() {
  LocalQuery q("distinct publisher", "citation.works");
  if (q.submit(g_server) < 0) {
    add_to_error_and_exit("unable to get list of pubishers from 'works' table: "
        "'" + q.error() + "'");
  }
  g_myoutput << "\nCurrent Publisher List:" << endl;
  for (const auto& r : q) {
    g_myoutput << "Publisher: '" << r[0] << "'" << endl;
  }
}

int main(int argc, char **argv) {
  atexit(clean_up);
  read_config();
  clean_cache();
  parse_args(argc, argv);
  connect_to_database();
  create_doi_table();
  fill_journal_abbreviations();
  fill_journals_no_abbreviation();
  fill_publisher_fixups();
  DOI_LIST doi_list;
  fill_doi_list(doi_list);
  for (const auto& e : g_services) {
    if (get<4>(e.second)) {
      g_mail_message << "Querying '" << e.first << "'." << endl;
      query_service(e.first, e.second, doi_list);
    }
  }
  print_publisher_list();
  g_server.disconnect();
  g_output.close();
  exit(0);
}
