# HEIC to JPEG API

Szybki serwis HTTP do konwersji plikow `HEIC/HEIF` do `JPEG`, zbudowany na `FastAPI`, `Pillow` i `pillow-heif`.
Projekt zachowuje kompatybilny kontrakt requestu oparty o pola:

- `file`
- `targetExtension`
- `quality`

Najwazniejsza zasada integracyjna jest prosta: klient moze przepiac sie na nowy URL bez zmiany payloadu requesta.

## Spis tresci

- [Co robi ten projekt](#co-robi-ten-projekt)
- [Najwazniejsze cechy](#najwazniejsze-cechy)
- [Kontrakt kompatybilnosci](#kontrakt-kompatybilnosci)
- [Endpointy](#endpointy)
- [Szczegoly requestu](#szczegoly-requestu)
- [Szczegoly response](#szczegoly-response)
- [Kody odpowiedzi](#kody-odpowiedzi)
- [Szybki start](#szybki-start)
- [Uruchomienie lokalne](#uruchomienie-lokalne)
- [Uruchomienie przez Docker Compose](#uruchomienie-przez-docker-compose)
- [Konfiguracja ENV](#konfiguracja-env)
- [Jak to dziala w srodku](#jak-to-dziala-w-srodku)
- [Test obciazeniowy Locust](#test-obciazeniowy-locust)
- [Wydajnosc i sizing](#wydajnosc-i-sizing)
- [Struktura projektu](#struktura-projektu)
- [Ograniczenia](#ograniczenia)
- [Troubleshooting](#troubleshooting)

## Co robi ten projekt

Serwis przyjmuje upload pliku `HEIC` lub `HEIF`, waliduje request, wrzuca zadanie do kolejki i przetwarza plik w tle na `JPEG`.
Odpowiedz jest zwracana jako strumien binarny `image/jpeg`.

Projekt nie jest generycznym "file converterem" w sensie biznesowym.
Faktycznie wspierana konwersja to:

- source: `heic`, `heif`
- target: `jpg`, `jpeg`

Warstwa HTTP zostala jednak przygotowana tak, aby zachowac legacy-compatible ksztalt requesta z polami `file`, `targetExtension`, `quality`.

## Najwazniejsze cechy

- kompatybilny payload requestu dla istniejacych klientow
- obsluga `HEIC/HEIF -> JPEG`
- per-request `quality` w zakresie `1-100`
- limit uploadu konfigurowany przez ENV
- kolejka zadan i workery watkowe
- ochrona przed przeciazeniem przez limit kolejki i estymowany czas oczekiwania
- response binarny `image/jpeg`
- best-effort zachowanie metadanych `EXIF`, `ICC profile`, `DPI`
- gotowy `Dockerfile`, `docker-compose.yml` i profil `loadtest`

## Kontrakt kompatybilnosci

To jest kluczowe zalozenie tego projektu.

Klient integracyjny nie musi zmieniac struktury requesta. Nadal moze wysylac:

- `file`
- `targetExtension`
- `quality`

Zmiana po stronie integracji moze ograniczyc sie do URL-a endpointu.

Przyklady zgodnych wariantow:

- `POST /convert`
- `POST /convert/jpg`
- `POST /convert/jpeg`
- `POST /convert-to-jpeg`

Uwagi:

- `POST /convert` oczekuje `targetExtension` w request body lub query string.
- `POST /convert/{target}` pozwala przeniesc target do URL-a.
- `POST /convert-to-jpeg` jest aliasem dla konwersji do `jpg`.
- Jesli ta sama informacja o `targetExtension` lub `quality` zostanie podana w kilku miejscach i wartosci beda sprzeczne, API zwroci `400`.

## Endpointy

| Metoda | URL | Opis |
| --- | --- | --- |
| `POST` | `/convert` | Glowny endpoint zgodny z kompatybilnym requestem |
| `POST` | `/convert/{targetExtension}` | Wariant z targetem w URL, np. `/convert/jpg` |
| `POST` | `/convert-to-jpeg` | Alias dla konwersji do `jpg` |
| `GET` | `/health` | Healthcheck i podstawowe metryki kolejki |

## Szczegoly requestu

### Content type

Request powinien byc wysylany jako:

```http
multipart/form-data
```

### Pola requestu

| Pole | Typ | Wymagane | Dozwolone wartosci | Domyslna wartosc | Opis |
| --- | --- | --- | --- | --- | --- |
| `file` | plik | tak | `*.heic`, `*.heif` | brak | Plik zrodlowy do konwersji |
| `targetExtension` | string | tak dla `/convert`, opcjonalne dla `/convert-to-jpeg` | `jpg`, `jpeg` | `jpg` tylko dla aliasu `/convert-to-jpeg` | Format docelowy |
| `quality` | int/string | nie | `1-100` | `100` | Jakosc JPEG dla pojedynczego requestu |

### Zasady walidacji

- `file` musi istniec
- `file` musi miec nazwe
- source musi byc rozpoznany jako `HEIC` lub `HEIF`
- `targetExtension` moze byc tylko `jpg` albo `jpeg`
- `quality` musi byc liczba calkowita w zakresie `1-100`
- pusty upload zwraca blad
- upload wiekszy niz limit zwraca blad

### Jak rozpoznawany jest format zrodlowy

API akceptuje plik, jesli spelniony jest co najmniej jeden z warunkow:

- `Content-Type` to `image/heic` lub `image/heif`
- rozszerzenie pliku to `.heic` lub `.heif`

To pozwala przejsc przez typowe przypadki, w ktorych klient ustawia poprawna nazwe pliku, ale nie zawsze poprawny naglowek MIME, albo odwrotnie.

## Szczegoly response

### Sukces

Przy poprawnej konwersji API zwraca:

- status `200`
- `Content-Type: image/jpeg`
- binarne dane JPEG w body

### Naglowki odpowiedzi

| Naglowek | Przyklad | Opis |
| --- | --- | --- |
| `Content-Disposition` | `attachment; filename="photo.jpg"` | Sugerowana nazwa pobieranego pliku |
| `X-Queue-Pending` | `0` | Aktualna liczba oczekujacych zadan w kolejce |

### Nazwa pliku wynikowego

Serwis zachowuje stem oryginalnej nazwy i podmienia rozszerzenie na wynikowe.

Przyklad:

- input: `IMG_0001.heic`
- output: `IMG_0001.jpg`

## Kody odpowiedzi

| Status | Kiedy wystepuje |
| --- | --- |
| `200` | Konwersja zakonczona sukcesem |
| `400` | Brak pola `file`, brak filename, niepoprawny `quality`, konflikt wartosci miedzy URL/form/query, pusty plik |
| `413` | Upload przekracza maksymalny rozmiar |
| `415` | Nieobslugiwany format zrodlowy albo nieobslugiwany target |
| `422` | Techniczna porazka konwersji obrazu |
| `503` | Kolejka jest pelna albo serwis jest chwilowo przeciazony |
| `504` | Zadanie nie zmiescilo sie w timeout-cie oczekiwania |

## Przyklady wywolan

### 1. Kompatybilny request przez glowny endpoint

```bash
curl -X POST "http://localhost:8000/convert" \
  -H "accept: image/jpeg" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@./photo.heic" \
  -F "targetExtension=jpg" \
  -F "quality=100" \
  --output converted.jpg
```

### 2. Target w URL

```bash
curl -X POST "http://localhost:8000/convert/jpg" \
  -H "accept: image/jpeg" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@./photo.heic" \
  -F "quality=85" \
  --output converted.jpg
```

### 3. Alias zgodny z intencja "convert to jpeg"

```bash
curl -X POST "http://localhost:8000/convert-to-jpeg" \
  -H "accept: image/jpeg" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@./photo.heic" \
  -F "targetExtension=jpg" \
  -F "quality=100" \
  --output converted.jpg
```

### 4. Parametry w query string

```bash
curl -X POST "http://localhost:8000/convert/jpg?quality=80" \
  -H "accept: image/jpeg" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@./photo.heic" \
  --output converted.jpg
```

## Health endpoint

### Request

```bash
curl "http://localhost:8000/health"
```

### Przykladowa odpowiedz

```json
{
  "status": "ok",
  "pending_jobs": 0,
  "workers": 8,
  "estimated_wait_sec": 0.0
}
```

### Znaczenie pol

| Pole | Opis |
| --- | --- |
| `status` | Ogolny stan aplikacji |
| `pending_jobs` | Liczba requestow oczekujacych w kolejce |
| `workers` | Liczba aktywnych workerow konwersji |
| `estimated_wait_sec` | Szacowany czas oczekiwania przed rozpoczeciem przetwarzania |

## Szybki start

### Najprostsza sciezka: Docker Compose

```bash
docker compose up --build -d api
```

Po starcie API bedzie dostepne pod:

```text
http://localhost:8000
```

Healthcheck:

```bash
curl http://localhost:8000/health
```

Zatrzymanie:

```bash
docker compose down
```

## Uruchomienie lokalne

### Wymagania

- Python `3.11+`
- zalecany Python `3.12`
- Node.js + Yarn, jesli chcesz korzystac z gotowych skryptow z `package.json`

### Instalacja zaleznosci

Wariant bezposredni:

```bash
python3 -m pip install -r requirements.txt
```

Wariant przez skrypty Yarn:

```bash
yarn install
yarn py:install
```

### Start developerski

Bezposrednio:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Przez Yarn:

```bash
yarn dev
```

### Start produkcyjny lokalny

Bezposrednio:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Przez Yarn:

```bash
yarn start
```

### Szybki check skladni

```bash
python3 -m compileall app loadtest
```

Lub:

```bash
yarn check
```

## Uruchomienie przez Docker Compose

Projekt zawiera gotowy `Dockerfile` oraz `docker-compose.yml`.

### Co robi obraz Docker

- bazuje na `python:3.12-slim-bookworm`
- instaluje runtime dependencies dla HEIF/HEIC: `libheif1`, `libde265-0`
- instaluje zaleznosci z `requirements.txt`
- kopiuje katalog `app/`
- uruchamia proces jako nie-root `appuser`

### Start API

```bash
yarn docker:up
```

albo:

```bash
docker compose up --build -d api
```

### Stop API

```bash
yarn docker:down
```

albo:

```bash
docker compose down
```

### Porty

| Serwis | Port hosta | Port kontenera |
| --- | --- | --- |
| API | `8000` | `8000` |
| Locust GUI | `8089` | `8089` |

### Healthcheck kontenera

Compose wykonuje healthcheck pod:

```text
http://127.0.0.1:8000/health
```

## Konfiguracja ENV

Konfiguracja pochodzi z:

- fallbackow w aplikacji (`app/config.py`)
- wartosci przekazywanych przez `docker-compose.yml`
- lokalnego pliku `.env`
- przykladowego `.env.example`

### Zmienne aplikacyjne

| Zmienna | Opis | Fallback aplikacji | Fallback w `docker-compose.yml` | `.env.example` |
| --- | --- | --- | --- | --- |
| `CONVERTER_WORKERS` | Liczba workerow konwersji | `cpu_count` | `8` | `2` |
| `CONVERTER_QUEUE_MAXSIZE` | Maksymalna liczba zadan w kolejce | `512` | `1024` | `128` |
| `CONVERTER_ENQUEUE_TIMEOUT_SEC` | Zachowane dla konfiguracji kolejki | `2.0` | `2.0` | `2.0` |
| `CONVERTER_JOB_TIMEOUT_SEC` | Timeout oczekiwania na wynik requestu | `30.0` | `30.0` | `30.0` |
| `CONVERTER_JPEG_QUALITY` | Jakosc fallback, gdy request nie poda `quality` | `100` | `100` | `100` |
| `CONVERTER_MAX_UPLOAD_MB` | Maksymalny rozmiar uploadu | `50` | `50` | `50` |

### Zmienne HTTP/runtime

| Zmienna | Opis | Fallback aplikacji lub runtime | Fallback w `docker-compose.yml` | `.env.example` |
| --- | --- | --- | --- | --- |
| `UVICORN_WORKERS` | Liczba workerow HTTP uvicorn | ustawiane przez komende startowa | `1` | `2` |
| `UVICORN_BACKLOG` | Rozmiar backlogu socketu | ustawiane przez komende startowa | `2048` | `4096` |
| `UVICORN_TIMEOUT_KEEP_ALIVE` | Keep-alive dla polaczen HTTP | ustawiane przez komende startowa | `5` | `5` |

### Zmienne infrastrukturalne i load test

| Zmienna | Opis | Fallback w `docker-compose.yml` | `.env.example` |
| --- | --- | --- | --- |
| `API_CPUS` | Limit CPU dla kontenera API | `8.0` | `2.0` |
| `API_MEM_LIMIT` | Limit RAM dla kontenera API | `8g` | `4g` |
| `HEIC_FILE` | Sciezka do pliku testowego dla Locusta | `/loadtest/assets/sample.heic` | `/loadtest/assets/sample.heic` |
| `REQUEST_TIMEOUT_SEC` | Timeout klienta load testowego | `60` | `60` |
| `LOADTEST_BASE_URL` | Host API dla Locusta | `http://api:8000` | `http://api:8000` |

### Przykladowy przeplyw pracy z `.env`

1. Skopiuj szablon:

```bash
cp .env.example .env
```

2. Dostosuj parametry do lokalnego srodowiska.

3. Uruchom:

```bash
docker compose up --build -d api
```

## Jak to dziala w srodku

Architektura jest celowo prosta i operacyjnie przewidywalna.

### Przeplyw requestu

1. FastAPI odbiera `multipart/form-data`.
2. Warstwa kontraktu waliduje `file`, `targetExtension` i `quality`.
3. API odrzuca requesty, gdy kolejka jest pelna lub estymowany czas oczekiwania jest zbyt duzy.
4. Plik jest czytany do pamieci z limitem rozmiaru.
5. Zadanie trafia do wewnetrznej kolejki.
6. Worker otwiera obraz przez `pillow-heif` i `Pillow`.
7. Obraz jest przeksztalcany do `JPEG`.
8. Serwis probuje zachowac `EXIF`, `ICC profile` i `DPI`.
9. Binarny JPEG wraca do klienta.

### Dlaczego kolejka

Kolejka pozwala:

- ograniczyc liczbe rownoleglych konwersji
- uniknac zbyt agresywnego blokowania event loop FastAPI
- lepiej kontrolowac przeciazenie serwisu
- raportowac przyblizony czas oczekiwania

### Metadane

Serwis zachowuje metadane best-effort:

- `EXIF`
- `ICC profile`
- `DPI`

Nie ma gwarancji, ze kazdy plik zrodlowy zachowa komplet metadanych po konwersji.

## Test obciazeniowy Locust

Repo zawiera gotowy profil `loadtest` w `docker-compose.yml` oraz scenariusz w `loadtest/locustfile.py`.

### Przygotowanie pliku testowego

Wrzuc plik `sample.heic` do:

```bash
./loadtest/assets/sample.heic
```

Mozesz tez wskazac inna sciezke przez `HEIC_FILE`.

### Start testu

```bash
yarn load:test
```

albo:

```bash
docker compose --profile loadtest up --build api loadtest
```

### GUI Locust

Po starcie otworz:

```text
http://localhost:8089
```

W GUI ustaw:

- liczbe uzytkownikow
- spawn rate
- moment startu i stopu testu

### Co wysyla Locust

Scenariusz obciazeniowy wysyla:

- `POST /convert`
- pole `file`
- `targetExtension=jpg`
- `quality=100`

### Wyniki

Katalog `loadtest/results` jest podmontowany do kontenera load testowego.
Mozesz go wykorzystac do eksportow raportow z GUI lub wlasnych rezultatow.

## Wydajnosc i sizing

Wydajnosc zalezy glownie od:

- rozmiaru i rozdzielczosci plikow `HEIC/HEIF`
- liczby workerow konwersji
- rozmiaru kolejki
- CPU i RAM kontenera
- timeoutow po stronie API i klienta

### Praktyczne zalecenia startowe

Dla srednich plikow mobilnych `HEIC`:

- `8 vCPU`
- `8 GB RAM`
- `CONVERTER_WORKERS=8`
- `CONVERTER_QUEUE_MAXSIZE=256` lub `512`

### Wazna uwaga o pamieci

Kolejka trzyma payloady w RAM.
To oznacza, ze zbyt duzy `CONVERTER_QUEUE_MAXSIZE` moze bardzo szybko zwiekszyc zuzycie pamieci.

Przyblizenie:

```text
RAM ~= runtime + workery + (QUEUE_MAXSIZE * sredni_rozmiar_pliku)
```

Przyklad:

- `QUEUE_MAXSIZE=1024`
- sredni plik `3 MB`

Sama kolejka moze zajac okolo `3 GB` RAM, zanim doliczysz runtime aplikacji i workery.

### Timeouty

Jesli uruchamiasz testy obciazeniowe, pilnuj zaleznosci:

```text
REQUEST_TIMEOUT_SEC >= CONVERTER_JOB_TIMEOUT_SEC
```

W przeciwnym razie klient moze przerwac polaczenie szybciej niz API zakonczy oczekiwanie na wynik.

## Struktura projektu

```text
.
|-- app/
|   |-- config.py        # ladowanie ustawien z ENV
|   |-- contracts.py     # kompatybilny kontrakt requestu i walidacja
|   |-- converter.py     # kolejka, workery i konwersja HEIC/HEIF -> JPEG
|   `-- main.py          # endpointy FastAPI
|-- loadtest/
|   |-- assets/          # pliki testowe dla Locusta
|   |-- results/         # miejsce na wyniki testow
|   `-- locustfile.py    # scenariusz obciazeniowy
|-- Dockerfile
|-- docker-compose.yml
|-- package.json
|-- requirements.txt
`-- README.md
```

## Ograniczenia

To warto przeczytac przed wdrozeniem:

- faktycznie obslugiwany input to `HEIC/HEIF`
- faktycznie obslugiwany output to `JPG/JPEG`
- response zwraca pojedynczy binarny `JPEG`, nie tablice base64 ani archiwum plikow
- plik requestu jest czytany do pamieci
- kolejka rowniez przechowuje dane w pamieci
- brak warstwy autoryzacji i rate limiting w samym projekcie
- brak trwalego storage i retry po restarcie procesu

## Troubleshooting

### `415 Unsupported file type`

Najczestsze przyczyny:

- plik nie jest `HEIC/HEIF`
- filename nie ma rozszerzenia `.heic` lub `.heif`
- klient wysyla nieprawidlowy `Content-Type`
- `targetExtension` ma inna wartosc niz `jpg` lub `jpeg`

### `400 Invalid request`

Najczestsze przyczyny:

- brak pola `file`
- brak `filename`
- `quality` poza zakresem `1-100`
- `quality` nie jest liczba calkowita
- sprzeczne wartosci `targetExtension` lub `quality` w kilku miejscach
- pusty plik

### `503 Queue is full` lub `Service is overloaded`

To znaczy, ze serwis osiagnal limit przyjmowania zadan.
Najczesciej trzeba:

- zmniejszyc ruch
- zwiekszyc CPU/RAM
- zwiekszyc liczbe workerow
- ostroznie dostroic `CONVERTER_QUEUE_MAXSIZE`

### Wysokie zuzycie RAM

Najpierw sprawdz:

- sredni rozmiar uploadowanego pliku
- `CONVERTER_QUEUE_MAXSIZE`
- liczbe rownoleglych workerow

Najczesciej pomaga obnizenie `CONVERTER_QUEUE_MAXSIZE`.

### Problem z lokalnym uruchomieniem na Windows

Jesli pracujesz w WSL, uruchamiaj komendy Python po stronie WSL, np.:

```bash
wsl bash -lc "cd /home/dev/projects/file-converter && python3 -m compileall app loadtest"
```

### Brak dekodowania HEIC lokalnie

Najbezpieczniejsza sciezka uruchomienia to Docker, bo obraz zawiera potrzebne biblioteki runtime:

- `libheif1`
- `libde265-0`

## Podsumowanie

Ten projekt jest wyspecjalizowanym API do konwersji `HEIC/HEIF -> JPEG`, ale z warstwa HTTP zaprojektowana pod zachowanie kompatybilnego requestu.
Jesli zalezy Ci na przepieciu integracji tylko po URL-u, to wlasnie taki jest docelowy model uzycia tego serwisu.
