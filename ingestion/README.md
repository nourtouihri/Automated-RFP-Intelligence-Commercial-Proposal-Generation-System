# Ingestion Microservice
## Description
This microservice ticks the multi-source crawler bonus point from the CSTAM book.
It exposes endpoint per source. Currently it has two sources and its architecture easily scales to accept more sources
## Design Choice
The ingestion microservice should be scalable. It should facilitate integrating new sources. This led to opting for **Chain of Responsibility**. It helps represent an abstract source-independant ingestion pipeline. Each source just implements its own fetching and mapping behaviour while the wiring and the workflow remains unchanged.

Each source only implements `BaseIngest` to fetch notices via api, and `BaseHandler` handles mapping the source-dependant notices into 1 general `Notice` schema. That schema is compatible with the detection microservice, so we don't need to propagate any modifications in the next microservices.

## Sources
The crawler fetches tenders from 2 sources: TED (European Union tenders) and SAM (USA tenders).

### TED
A public procurement portal for EU countries. Extensive, free, and well-documented. <br>
This is an example of a tender:
```json
{
    "notice-identifier": "ef50e61d-c40b-45e8-9c8c-6ab2a244fc96",
    "deadline-receipt-request": [
        "2031-07-23T23:59:00+02:00"
    ],
    "description-lot": {
        "eng": [
            "This call for expressions of interest is organised on the basis of Article 242 of the Financial Regulation . The purpose of this call for expressions of interest is to set up a list of external experts in the domains of legal data, reference data management, and data management and data governance for the Publications Office of the European Union (EU Publications Office). The experts will provide support in the creation of new products, services and/or tools in these domains. The following profiles are foreseen: (a) legal data expert; (b) reference data management expert; (c) expert in data management and data governance."
        ]
    },
    "notice-type": "pin-cfc-standard",
    "publication-number": "734875-2026",
    "organisation-country-buyer": [
        "LUX"
    ],
    "publication-date": "2026-10-23+02:00",
    "links": {
    "xml": {
        "MUL": "https://ted.europa.eu/en/notice/734875-2026/xml"
        //....
    },
    "pdf": {
        //...
        "ENG": "https://ted.europa.eu/en/notice/734875-2026/pdf",
        //...
    },
    "pdfs": {
        "ENG": "https://ted.europa.eu/en/notice/734875-2026/pdfs"
    },
    "html": {
        "BUL": "https://ted.europa.eu/bg/notice/-/detail/734875-2026",
        "SPA": "https://ted.europa.eu/es/notice/-/detail/734875-2026",
        //...
        "ENG": "https://ted.europa.eu/en/notice/-/detail/734875-2026",
    },
    "htmlDirect": {
        "BUL": "https://ted.europa.eu/bg/notice/734875-2026/html",
        "SPA": "https://ted.europa.eu/es/notice/734875-2026/html",
        // ...
        "ENG": "https://ted.europa.eu/en/notice/734875-2026/html",
    }
    },
    "organisation-name-buyer": {
        "eng": [
            "Publications Office of European Union"
        ]
    },
    "notice-title": {
        "hun": "Luxemburg – IT-szolgáltatások: tanácsadás, szoftverfejlesztés, internet és támogatás – Call for expressions of interest (CEI) for external experts in the domains of legal data, reference data management, and data management and data governance for the Publications Office of the European Union (EU Publications Office).",
        //...
        "eng": "Luxembourg – IT services: consulting, software development, Internet and support – Call for expressions of interest (CEI) for external experts in the domains of legal data, reference data management, and data management and data governance for the Publications Office of the European Union (EU Publications Office)."
    },
    "description-proc": {
        "eng": "This call for expressions of interest is organised on the basis of Article 242 of the Financial Regulation . The purpose of this call for expressions of interest is to set up a list of external experts in the domains of legal data, reference data management, and data management and data governance for the Publications Office of the European Union (EU Publications Office). The experts will provide support in the creation of new products, services and/or tools in these domains. The following profiles are foreseen: (a) legal data expert; (b) reference data management expert; (c) expert in data management and data governance."
    }
}
```

### SAM
A public procurement portal for US tenders. It has an API that fetches opportunities (tenders) <br>
This is an example of a notice:
```json
"noticeId": "784ebfc3be864465abb7876bd175286a",
"title": "NEW - Air Force Installation and Mission Support Center (AFIMSC) Streamlining Procurement for Effective Execution & Delivery (SPEED) Commercial Solutions Opening (CSO)",
"baseType": "Combined Synopsis/Solicitation",
"description": "https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid=784ebfc3be864465abb7876bd175286a",
"fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE.AIR FORCE MATERIEL COMMAND.AF INSTALLATION & MISSION SUPPORT CENTER.FA8903  772 ESS PK",
"officeAddress": {
    "countryCode": "USA",
},
"pointOfContact": [
    {
    "fax": "",
    "type": "primary",
    "email": "michael.grasso.3@us.af.mil",
    "phone": "3804578637",
    "fullName": "Michael Grasso"
    },
    {
    "type": "secondary",
    "email": "krystle.zapata.1@us.af.mil",
    "phone": "3804599768",
    "fullName": "Krystle M. Zapata"
    }
],
"postedDate": "2026-09-29",
"resourceLinks": [
    "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/0c1a20d579124d139f64cbc68532a7ea/download",
    "..."
],
"responseDeadLine": "2030-08-29T05:00:00-05:00",
"type": "Combined Synopsis/Solicitation",

"uiLink": "https://sam.gov/workspace/contract/opp/784ebfc3be864465abb7876bd175286a/view"
```

## Workflow
- n8n branches into 2 different groups: one for TED ingestion and the other for SAM
- For each group,
    - n8n initializes the page counter.
    - It fetches a batch of `INGEST_LIMITS`-sized tenders from the current source page (30 by default).
    - It maps each tender to the schema accepted by the detection service.
    - It passes the mapped batch to the next stage of the pipeline.
    - It increments the page counter and fetches the next batch.
    - It repeats the mapping and forwarding steps for each page until it reaches the final page.
    - It stops the ingestion process after the final page and passes the final batch to the rest of the pipeline.
- The result of each group are then mapped into 1 json response
- The mapped results are then passed to the next steps in the pipeline

## Env Variables
This module uses environment variables. They're both defined in `.env.example` and in `docker-compose.yml`. <br>
Here's what every variable signifies:

### `INGEST_SOURCES`
Comma-separated list of enabled ingestion sources, for example:
```bash
INGEST_SOURCES=TED,SAM
```
This defines the **canonical order** every other ingestion variable follows: the first entry here corresponds to the first API key in `INGEST_API_KEYS` and to the first limit in `INGEST_LIMITS`.

### `INGEST_API_KEYS`
Comma-separated API keys, **one entry per source, in the exact same order as `INGEST_SOURCES`**.
```bash
INGEST_API_KEYS=,SAM-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```
- TED's search API is public, so its slot stays **empty** (the first entry above is an empty string before the comma).
- SAM (SAM.gov) requires a key: get one at https://sam.gov → Account Settings → API Key, and put it in its source's slot.

### `INGEST_LIMITS`
Comma-separated per-source **fetch limit** (number of tenders fetched per page), **one entry per source, in the exact same order as `INGEST_SOURCES`**.
```bash
INGEST_LIMITS=30,30
```
With `INGEST_SOURCES=TED,SAM`, the example above fetches 30 TED notices per page and 30 SAM opportunities per page.
- Changing it also rescales the `page_cap` the service reports, so the n8n workflow naturally stops at the right final page.
- A source without a valid positive integer (missing entry, empty, non-numeric, zero) falls back to the built-in default of **30**.
- Tweak it to trade freshness scan depth against API load / runtime.

