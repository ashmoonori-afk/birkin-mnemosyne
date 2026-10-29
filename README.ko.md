![birkin-mnemosyne - 에이전트를 위한 작은 다국어 메모리: 세 개의 노트 카드가 빛나는 실로 검색 렌즈에 연결된 모습](https://raw.githubusercontent.com/ashmoonori-afk/birkin-mnemosyne/main/docs/assets/hero.png)

# birkin-mnemosyne

[랜딩 페이지](https://birkin-mnemosyne.vercel.app/ko/)

birkin-mnemosyne은 개인 에이전트를 위한 로컬 Markdown 메모리입니다. 다국어
BM25 검색, 사용 기반 감쇠(decay)와 영역(zone) 우선순위, 그리고 결정적 실행기가
파일 작업 범위를 제한하는 공급자 이식형 큐레이션을 제공합니다. 코어는 런타임
의존성이 전혀 없고, 노트를 저장하거나 검색하는 데 모델이나 API 키가 필요하지
않습니다. 노트는 읽기, grep, diff가 가능한 형식 그대로 유지되며, 선택 사항인
MCP 서버가 볼트를 에이전트 클라이언트에 연결하고, 옵트인 의미 모드(opt-in
semantic mode)가 의미 기반 검색을 더해 줍니다.

## 0.8.0: 다른 언어로 물어도 맞는 노트를 찾아요(키를 넣었을 때만).

`MNEMOSYNE_RERANK_API_KEY`를 넣으면 `recall()`(MCP 도구 `memory_kibitzer_candidates` 포함)이 번역한 질문으로도 후보를 찾고, 외부 판정 모델로 순서를 다시 매겨요. 처음 보는 6개 언어 질문 1,432개에서 정답이 5위 안에 든 질문이 298개에서 1,028개로 늘었어요(3.45배, 2026년 10월 25일 측정, PR #91). 질문 하나에 약 0.0081달러와 약 4초가 드는 것으로 추정되고, 키가 없거나 `MNEMOSYNE_RERANK=off`면 지금처럼 내 컴퓨터 안에서만 돌아요.

## 0.7.1: 중첩 폴더와 터미널 읽기

여러 단계로 나뉜 폴더의 Markdown 메모도 기본 검색에 포함됩니다. 공백이나
한글이 있는 폴더와 중첩된 가져오기를 그대로 사용할 수 있습니다. 숨김 파일,
캐시 폴더와 링크는 제외합니다. 영역은 전체 상대 폴더 경로를 사용하며,
보관할 때 원래 하위 경로를 유지하고 되돌리면 정확한 경로와 바이트를 복원합니다.
0.7.1은 파일 이름이 겹치면 가장 최근 파일만 선택했으며,
0.7.2는 나머지 파일도 상대 경로 키로 유지합니다.

배포된 패키지에서 읽기 전용 `search`, `list`, `show`, 반복 가능한 라벨 필터,
`--version`, 기록에 따른 `undo`를 사용할 수 있습니다. 터미널과 MCP는
문서에 적힌 같은 저장소 기본값을 사용합니다. 모델이 새로 필요해지거나
라벨이 검색 점수에 들어가지는 않습니다.

## 설치

Python >= 3.10이 필요합니다. PyPI에서 설치하세요:

```bash
pip install "birkin-mnemosyne==0.8.0"
```

체크아웃 상태에서 쓰는 개발·벤치마크 명령은 다음과 같습니다:

```bash
pip install -e .                 # 표준 라이브러리만 쓰는 코어
pip install -e ".[dev]"          # pytest, ruff
pip install -e ".[bench]"        # fastembed, numpy: 임베딩 베이스라인 전용
pip install -e ".[mcp]"          # 공식 MCP SDK와 서버
pip install -e ".[semantic]"     # 선택 사항인 의미 기반 검색
```

엑스트라는 모두 선택 사항입니다. `[bench]`는 임베딩 베이스라인을 재현할 뿐
의미 검색을 켜지 않습니다. 명시적인 의미 모드 준비는 아래를 참고하세요.

## 에이전트 사용자를 위한 빠른 시작

아래 명령은 0.8.0에 포함됩니다. 배포된 MCP 추가 패키지를 설치하면
소스 체크아웃 없이 에이전트에 연결할 수 있습니다.
코딩 에이전트에 기억을 연결하고, 무엇을 저장했는지 터미널에서 확인하세요:

```bash
pip install "birkin-mnemosyne[mcp]==0.8.0"
claude mcp add --scope user mnemosyne -- mnemosyne-mcp --vault ~/mnemosyne

# 새 에이전트 세션을 열고 "Release checklist"라는 제목으로
# 릴리스 체크리스트 메모를 저장하도록 요청한 뒤 아래에서 확인하세요.
mnemosyne --version
mnemosyne --vault ~/mnemosyne search "릴리스 체크리스트"
mnemosyne --vault ~/mnemosyne list
mnemosyne --vault ~/mnemosyne show release-checklist
```

다른 클라이언트(Claude Desktop, Cursor, Codex CLI, IDE)는
[MCP 서버 섹션](#mcp-서버claude-code-claude-desktop-codex-cli-cursor)을 보세요.
`search`, `list`, `show`는 MCP 도구 `memory_search`, `memory_list`,
`memory_get_note`와 같은 필드의 JSON을 출력합니다. 읽기 전용이라 사용 기록으로
세지 않으므로 사용 빈도 순위를 바꾸지 않습니다. 없는 메모를 `show`하면 종료 코드
1, 존재하지 않는 볼트 폴더는 종료 코드 2이며 폴더를 만들지 않습니다.

`search`나 `list`에 `--label namespace:value`를 붙이면 라벨로 좁힐 수 있습니다.
여러 번 지정하면 모든 라벨을 가진 메모만 선택합니다(AND). 순위 계산이나
페이지 나누기 전에 필터링하며, `list`의 `label_counts`는 현재 페이지가 아닌
조건에 맞는 전체 메모의 라벨 수를 반환합니다.

외부 Markdown 파일의 확장자는 대소문자를 구분하지 않습니다(`.md`, `.MD`, `.Md`).
가져오기의 `.txt`, `.json`도 동일하며 원래 파일명과 원문 바이트를 보존합니다.
점으로 시작하는 숨김 파일은 일반 메모 검색에서 제외하며, 공개된 zone 폴더
안의 숨김 파일도 제외합니다.

모든 `mnemosyne` 명령은 같은 순서로 볼트를 찾습니다: `--vault`(명령 이름 앞이나
뒤), 없으면 `$MNEMOSYNE_VAULT`, 없으면 `mnemosyne-mcp`와 같은 기본값
`~/.birkin-mnemosyne/vault`. `init`만 마지막 단계에서 현재 폴더를 씁니다. 셸이
`~`를 따옴표 안에 남겨도 홈 폴더로 확장합니다. `MNEMOSYNE_VAULT`를 한 번
설정하면 터미널과 MCP 서버가 `--vault`를 반복하지 않아도 같은 볼트를 씁니다.

## 첫 실행 (First run)

v0.7.0부터 `mnemosyne init`은 파일을 바꾸지 않고 첫 정리 계획을
보여줍니다. 표준 라이브러리만 쓰는 코어로 동작하며 모델이나 API 키가
필요하지 않습니다:

```bash
mnemosyne init --vault my_vault
mnemosyne init --vault my_vault --apply

# 외부 Markdown을 가져올 때는 적용 명령에도 같은 옵션을 넣으세요.
mnemosyne init --vault my_vault --import ./markdown_export
mnemosyne init --vault my_vault --import ./markdown_export --apply
```

`--vault`를 생략하면 `$MNEMOSYNE_VAULT`가 있을 때 그 폴더를, 없으면 현재 폴더를
사용합니다. JSON 출력의 `vault` 키에 실제로 작업한 절대 경로가 나옵니다. 기존
`mnemosyne-index --vault my_vault init`도 같은 진입점을 사용합니다.
JSON 출력에는 계획과 메모·주제 수, INDEX 토큰 추정치, 경고, 검증 상태가
나옵니다. 미리보기는 `planned`이며, 적용 후에는 상주 INDEX를 독립적으로
검증하고 드리프트를 확인합니다. 모든 메모가 하나의 시작 번들에 들어간다는
뜻은 아닙니다.

중복과 겹침·충돌 가능성이 있는 후보를 보고하지만 어느 쪽이 맞는지 정하거나
자동으로 병합·보관·삭제하지 않습니다. 빠진 `title`, `type`, `tags`는 기존의
바이트 단위 검토 저널을 통해 보완하며 기존 필드와 본문 바이트를 보존합니다.
해석이 불분명한 헤더와 분할 영수증에 묶인 바이트는 경고와 함께 유지합니다.
출력에 `undo_transaction`이 있으면
`mnemosyne --vault my_vault undo --transaction <undo_transaction>`
(또는 `Consolidation(vault).undo(transaction_id)`, `memory_review_undo` 도구)로
원래 메모 바이트를 복구할 수 있습니다. 같은 명령으로 적용된 handoff fold나
검토 답변도 되돌릴 수 있습니다.
추가된 가져오기 파일·주제 목차·INDEX 경로는 되돌린 뒤에도 남습니다.

주제 문서는 태그, 원래 폴더, 메모 유형으로 묶은 결정적인 원문 링크 목차입니다.
원문마다 목차와 별도로 읽기 경로가 등록됩니다. 기존 별칭을 유지하며,
큰 INDEX는 기존의 완전한 주제 목차를 사용하거나 UTF-8 바이트/4 예산 초과를
경고할 뿐 경로를 버리지 않습니다. `--max-tokens`로 경고 예산을 바꿀 수 있습니다.
변경 없는 재실행은 결과물을 재사용하고 새 저널을 만들지 않습니다.
바뀐 대상 파일은 덮어쓰지 않고 거부하며 미완료 저널은 체크된 복구가 먼저 필요합니다.

## 30초 사용법

```python
from birkin_mnemosyne import VaultMemory

mem = VaultMemory({"vault_path": "my_vault"})
mem.write_note(
    "Ingress DNS",
    "nginx ingress resolves service DNS; allow HTTPS through the firewall.",
    zone="devops",
)
for hit in mem.dex.search("ingress dns"):
    print(hit)
# 검색 후보마다가 아니라 에이전트가 실제로 쓴 노트를 강화합니다.
mem.dex.record_access("ingress-dns")
```

기존 볼트라면 `Mnemosyne("my_vault")`를 만들고 `refresh()`를 호출한 뒤
`search(query)`를 쓰세요. 유니코드 정규화, 악센트 폴딩, 라틴 접두사 어간,
한글·한자·가나 바이그램이 다국어 어휘 매칭을 지원합니다. 파일 변경은
인덱스에 반영됩니다. 라이브러리를 통해 쓴 노트는 즉시 검색되며, `search()`는
라이브러리 밖(예: Obsidian)에서 생긴 편집을 2초에 최대 한 번 확인합니다
(`refresh()`는 즉시 확인). 압축 캐시는 다시 만들 수 있고, 사용
이력은 따로 유지됩니다. 사용 감쇠와 영역 활동이 순위를 조정합니다.

### 검색 시점에 쿼리 확장(선택)

매칭은 어휘 기반이라 노트와 다르게 표현된 질문은 놓칠 수 있습니다. 호스트
모델은 검색할 때 자신의 쿼리를 스스로 넓힐 수 있습니다. 아무것도 저장되지
않고 인덱스도 건드리지 않으며, `expansions` 없이 검색하면 이전과 같은
순위를 냅니다:

```python
mem.search(
    "why can't the pods find each other by name",
    expansions={
        "synonyms": ["service discovery", "name resolution"],  # 가중치 0.75
        "keywords": ["Namensauflösung", "Dienst"],   # 0.75: 다른 언어(들)
        "related": ["ingress", "firewall"],                    # 0.4
        "note_line": "The ingress resolves service DNS names.",  # 0.4
    },
)
```

쿼리 자체 단어의 가중치는 1.0이며, 그 단어를 모두 포함한 노트가 1위를
유지합니다. MCP에서는 같은 네 필드가 `memory_search`의 파라미터입니다.
벤치마크 테스트 분할(10,000개 노트)에서 질문만 본 두 모델이 쓴 확장이
패러프레이즈 MRR을 0.204에서 0.981과 0.952로 올렸습니다. 질문과 확장 모두
모델이 작성했으므로 상한선으로 읽어 주세요:
[검색 시점 쿼리 확장](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#latest-main-replay-2026-10-11).

## 언어를 넘는 회상 재정렬(호스팅 모델, 키를 넣으면 켜짐)

질문과 다른 언어로 쓴 노트도 찾아 줍니다. 판정 모델 키를 설정하면
`KibitzerAdapter.recall()`과 MCP 도구 `memory_kibitzer_candidates`가 자동으로
재정렬합니다. 키가 없으면 아무것도 밖으로 보내지 않고 평소 BM25 순위를 돌려줍니다.
`select()`, `search()`와 표준 라이브러리 코어는 모델을 부르지 않습니다.

```bash
export MNEMOSYNE_RERANK_API_KEY=...        # OpenGateway 키. 넣으면 재정렬이 켜짐
export MNEMOSYNE_RERANK_TRANSLATOR=api     # 선택: 영어·한국어 번역 질의 추가
export MNEMOSYNE_RERANK=off                # 끄기 스위치. 키보다 우선
```

```python
from birkin_mnemosyne import KibitzerAdapter

result = KibitzerAdapter("my_vault").recall("클러스터 오토스케일러는 언제 노드를 추가하나요?")
print(result.selector, result.fallback)    # 재정렬이 돌면 "crosslingual-rerank", None
for hit in result.candidates:
    print(hit.path, hit.score)             # 점수는 낮을수록 좋음
```

| 설정 | 효과 |
|---|---|
| `MNEMOSYNE_RERANK_API_KEY` | 호스팅 판정 모델(OpenGateway의 `sionic-ai/jev-omni`)을 켭니다. 일반 `OPENGATEWAY_API_KEY`는 일부러 읽지 않습니다. 다른 도구용으로 넣어 둔 키 때문에 노트가 전송되는 일을 막기 위해서입니다. |
| `MNEMOSYNE_RERANK_TRANSLATOR` | 질의의 영어·한국어 번역을 만들 `get_completer` 공급자(`claude`, `codex`, `api`, `gemini`, `local`). 측정한 구성은 번역 질의를 썼습니다. 이 설정이 없으면 원래 질의만으로 재정렬하며, 이 방식은 측정하지 않았습니다. |
| `MNEMOSYNE_RERANK=off` | 끄기 스위치(`0`, `false`, `no`도 됨). 아무것도 보내지 않고 경고도 남기지 않습니다. 한 번만 끄려면 `recall(rerank=False)`. |
| `MNEMOSYNE_RERANK_TIMEOUT` | 판정 요청 하나의 제한 시간(초). 기본 30. |

코드에서 클라이언트를 직접 넘길 수도 있습니다: `KibitzerAdapter(vault, decide=..., complete=...)`.

**기존 순위로 돌아가는 경우.** `recall()`은 BM25 순위를 돌려주고 이유를
`result.fallback`에 적습니다.

- `no-key`: 키가 없음. 어댑터마다 경고 한 번.
- `error`: 판정·번역 요청이 실패했거나, 시간을 넘겼거나, 응답 형식이 틀렸거나,
  설정값이 잘못됨. 그 호출에 경고 한 번. 일부만 재정렬한 결과는 절대 돌려주지
  않고, 첫 실패 뒤 대기 중인 요청은 취소합니다.
- `off`, `disabled`: 끄기 스위치가 켜짐. 경고 없음.
- `limit`: 재정렬은 노트 다섯 개를 남기므로, 5보다 큰 limit은 요청 없이 BM25를 씁니다.

실패하면 기존 순위 대신 `RerankError`를 받고 싶다면
`select_crosslingual(query, decide=..., views=...)`를 그대로 쓸 수 있습니다.

**보내는 내용.** 판정 모델에는 원래 질의와, 후보 노트마다 설명과 1,500자 발췌만
보냅니다. 번역 요청에는 질의만 보냅니다. `system/`, `_archive/`, 만료된 노트,
이미 보여 준 노트와 제외한 경로는 보내기 전에 빠지고, 비밀값처럼 보이는 문자열은
일반 회상과 같이 가립니다. 자동 재시도는 없습니다.

**순위를 정하는 방법.**

1. 원래 질의와 번역 질의마다 BM25와 TF-IDF 코사인으로 상위 32개 노트를
   가져옵니다. 원래 질의의 결과를 앞에 두고 중복은 뺍니다.
2. 판정 모델이 카드를 최대 8장씩 묶어 점수를 매깁니다. 판정 모델에는 원래
   질의만 보냅니다.
3. 두 검색 방식의 점수를 평균해 다섯 개를 남깁니다.
4. 다섯 개의 모든 쌍을 양쪽 순서로 비교하고, 순서 영향을 상쇄한 선호 합으로
   정렬합니다. 완전히 같으면 3단계 순서를 지킵니다.

연구와 같이 판정 요청은 동시에 최대 다섯 개까지 보냅니다.

**확인된 결과(처음 보는 검증 세트, 2026년 10월 25일).** 연구 실행기로 6개
언어(zh, ja, ko, es, fr, en) 새 질문 1,440개를 한 번 측정했습니다. 절반은 같은
언어, 절반은 다른 언어 문서를 찾는 질문입니다. 방법을 고를 때 쓴 질문과 번호·
문장이 하나도 겹치지 않습니다. 채점 전에 번역 품질 검사를 통과하지 못한 원문
질문 두 개를 모든 번역본과 함께 뺐습니다. 비교마다 8건이 빠져 **1,440개 중
1,432개**가 남았고, 언어별 문제 수가 조금 다릅니다. 정답 문서가 첫 후보 다섯 개
안에 든 질문은 설치된 Kibitzer 회상 **298개에서 1,028개**로 늘었습니다. 언어별
평균 성공률은 20.8%에서 71.8%로, **3.45배이고 묶음 단위 95% 구간은
3.14~3.81배**입니다. 미리 정한 기준(3배 이상, 구간 하한도 3배 이상, 어떤 언어나
같은 언어 질문도 하락하지 않음)을 6개 언어 모두 통과했습니다.

| 질의 언어 | 이전 | 이후 |
|---|---:|---:|
| zh | 38/239 | 151/239 |
| ja | 52/239 | 172/239 |
| ko | 75/238 | 184/238 |
| es | 46/239 | 176/239 |
| fr | 25/239 | 156/239 |
| en | 62/238 | 189/238 |

한계도 함께 읽어 주세요. 이 지표는 관련 문서가 후보 다섯 개 안에 드는지이지,
답의 정확도가 아닙니다. 질문은 새것이지만 문서는 같은 공개 말뭉치 계열이고,
질문 64개는 이전 질문과 같은 문서를 공유합니다. 수치는 연구 실행기로 잰 값입니다.
연구에서 저장한 판정 응답 58,498건을 이 패키지의 카드·요청·평균·쌍 비교 코드로
다시 돌리자, 1,432개 질문 모두 같은 다섯 노트를 같은 순서로 골랐고 요청 내용도
한 바이트도 다르지 않았습니다. 다만 검색 단계는 이 확인에 들어가지 않습니다.
패키지는 자체 토크나이저를 쓰고, 연구는 연구용 검색기를 썼습니다.

앞서 2,400개 질문에서 얻은 결과(485개에서 1,602개, 3.30배, 구간 3.05~3.58)는
방법을 고르는 동안 같은 문제를 다시 쓴 것이라 선택 근거이지 확인 결과가
아닙니다. 과거 상위 2개 검사에서는 452/524(기준 425), SciFact 231/300(기준 224),
한국어 MIRACL 137/213(기준 107)이었습니다. 쌍 비교가 없는 직전 방식은 한국어
세트에서 142개였지만 SciFact 기준에 못 미쳤습니다.

**비용과 지연.** 질의 하나에 판정 요청은 `ceil(BM25 카드/8) + ceil(코사인 카드/8) + 20`건,
검증 세트에서는 평균 약 41건(점수 21건, 쌍 비교 20건)이었습니다. 판정 비용은
**질의당 평균 0.0081달러**입니다(입력 토큰당 0.0000000378달러로 계산한 추정치,
청구서 금액 아님). 번역 요청 두 건은 쓰는 번역 공급자 요금이 따로 듭니다. 측정된
판정 요청 하나는 평균 0.77초(점수), 0.20초(쌍 비교)였습니다. 다섯 개씩 동시에
보내면 번역 전 질의당 약 4초, 하나씩 보내면 약 20초입니다. 요청 시간으로 계산한
추정치이며, 이 모듈의 처음부터 끝까지 시간을 잰 값은 아닙니다.

## 항상 로드되는 메모리 INDEX(선택)

언제 읽어야 하는지(읽을 시점)에서 어떤 문서인지로 이어지는 **완전한 지도**를 시작
컨텍스트에 항상 담아 두고, 세부 내용은 필요할 때만 여는 기능입니다. INDEX는
v0.6.0부터 사용할 수 있습니다. 아래 설명하는 태스크 결합 읽기와 2단계 주제 맵은
v0.7.0부터 사용할 수 있습니다.

```python
from birkin_mnemosyne import MemoryIndex

# 위 예제에서 만든 것 같은 기존 노트를 등록합니다.
index = MemoryIndex("my_vault")
index.register("Ingress DNS", "devops/ingress-dns.md")
print(index.render())                 # 항상 로드되는 완전한 지도
opened = index.open("Ingress DNS")     # 정확한 트리거; 완전한 문서
```

`.mnemosyne-memory-index/` 디렉터리가 옵트인 표시입니다. 이 디렉터리가 없는
볼트는 레거시 동작을 유지합니다. 관리되는 시작·다이제스트·호스트 표면은 완전한
상주 맵을 유지합니다. 예산을 넘는 읽기는 경고만 하고 경로나 주제를 절대
제거하지 않습니다. INDEX 제거, 만료, 자동 정리 작업은 없습니다. 호스트는
재시작 사이에 `required=True` 또는 `--require-memory-index`를 유지하고, 컨텍스트
압축 후에는 완전한 INDEX를 다시 읽어야 합니다. 정확한 트리거는 믿을 수 있지만,
어휘 매칭과 BM25 폴백은 의미적 보장이 아닙니다.

v0.7.0부터 태스크 결합 읽기를 쓸 수 있습니다. 호스트가 행동하기 전에
`StartupReader("my_vault").read([], task="Check Ingress DNS")`를 호출하면,
어휘 매칭된 문서를 선택적 조회의 top-k 상한이나 검색 폴백 없이 전체 내용으로
돌려줍니다. 같은 `task`를 MCP의 `memory_startup_read` / `memory_startup_verify`에
넘기세요. 인덱스된 Hermes `prefetch`는 이 경로를 자동으로 사용합니다. 어휘
한계와 완전 읽기 실패 동작은 아래 사용 가이드를 참고하세요.

v0.7.0부터 렌더러는 단일 구조(flat) INDEX와 더 작은 2단계 주제 맵 중 하나를 선택합니다.
주제는 완전한 부모 디렉터리 경로를 따르고, 모든 경로는 자신의 완전한 주제
뷰에 남아 있습니다. `index.read(topic="dir:devops")`와 MCP의
`memory_index_read(topic="dir:devops")`가 그 주제를 확장합니다. 태스크 결합
시작은 한 번의 라우팅 스냅샷에서 매칭된 주제 뷰와 그 문서를 자동으로
포함합니다. 같은 문서의 별칭은 더 짧을 때만 라벨을 공유합니다. 조건이나
대상이 제거되지 않습니다. 선택된 레이아웃은 모델별 토크나이저가 아니라
선언된 바이트/4 추정값을 사용합니다.

간결한 상주 텍스트가 필요하면 `.render()` 또는 `view.context`를 쓰세요.
기본 `read().entries`는 여전히 모든 원래 매핑을 돌려주며, 그 완전한 구조화
결과가 상주 텍스트와 같은 비용이라고 주장하지 않습니다.

```bash
mnemosyne-index --vault my_vault check
mnemosyne-index --vault my_vault split handoff.md          # 읽기 전용 미리보기
mnemosyne-index --vault my_vault split handoff.md --apply  # 명시적 마이그레이션
```

분할기는 모든 소스 바이트를 보존하고 완전한 줄별 커버리지 표를 출력합니다.
체커는 고아, 매달린 경로, 손실된 커버리지를 보고합니다. MCP는
`memory_index_register`, `memory_index_read`, `memory_open_trigger`,
`memory_index_check`, `memory_index_split`을 노출합니다. 볼트를 백업할 때는
캡처된 소스 리비전을 포함해 `.mnemosyne-memory-index/`와
`.mnemosyne-reviews/`를 보관하세요.

**2026-10-11**, main `876ad40`의 최신 공개 재실행에서는 가상 대형 노트의
전체 시작 페이로드가 **45,128에서 1,297 o200k_base 토큰**으로 줄었습니다.
상주 INDEX만 세면 144토큰이며, 30개 경로와 소스 155,749바이트가 모두
보존됩니다. 별도로 고정된 Sol·Claude 답변 세트는 각각 **12/12**를 유지하며
정확도 향상은 아닙니다. 작은 노트의 합산 태스크 비용은 Sol 199-221토큰
(12/12가 전체 원본보다 비쌈), Claude 229-432토큰(0/12가 더 비쌈)입니다.
서로 다른 측정이며 대형 코퍼스의 태스크 정확도를 측정한 것은 아닙니다.

| 최신 공개 태스크 전달 재실행 | 결과 |
|---|---:|
| 필요한 본문 전체를 받은 긍정 태스크 | 12/12 |
| 정확히 비어 있는 부정 태스크 | 4/4 |
| 바이트가 정확하고 새로 검증된 전체 태스크 | 16/16 |
| 추가 문서 전달 | 1 |
| 확장 fixture 전체 시작 / 상주 INDEX, o200k_base 토큰 | 1,036 / 814 |

확장 fixture는 240개 문서, 12개 주제에 걸친 480개 경로를 모두 보존합니다.
기계적인 전달 검사이지 모델의 지시 준수나 의미적 정밀도는 아닙니다.

익명 집계만 공개한 별도의 **2026-10-11 교체 비공개 스냅샷** 측정에서는
26개 태스크의 시작 비용이 **2,193 -> 2,193**, 전체 실행이
**211,935 -> 177,359** o200k_base 토큰(16.3% 감소)입니다.
완전 전달은 **25/26 -> 26/26**, 추가 문서 전달은 **30 -> 12**로 바뀝니다.
전체 실행 합계는 완전한 태스크 내부 컨텍스트를 세며 도구 JSON이나
JSON-RPC 프레이밍은 제외합니다. 과거 비공개 스냅샷과는 다른 코퍼스이고
이번 공개 재실행에서는 다시 측정하지 않았습니다.

[사용·복구 가이드](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/memory-index-guide.md)와
[측정값·분모·회귀](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/memory-index-results.md)를 참고하세요.

## 레이블(namespace:value) (0.7.0)

노트 프론트매터의 `labels` 필드에는 `project:Infra`, `lang:ko`처럼 읽기 쉬운
`namespace:value` 라벨을 담을 수 있습니다. 라벨은 모델이나 API 키 없이
결정적으로 생성되며, 저장·검색·목록 어디서든 그대로 노출됩니다. 라벨은 검색
질문어가 아니고 순위를 올리는 점수 텍스트에도 들어가지 않습니다. 태그·타이틀·
본문이 검색되는 방식은 변하지 않습니다.

### 형식과 정규화

라벨은 첫 콜론으로 나뉜 비어 있지 않은 네임스페이스와 값입니다. 저장 시에는
NFC 정규화, 바깥 공백 제거, **네임스페이스 소문자화**, 정렬·중복 제거가
적용되며 **값의 대소문자·철자는 보존**됩니다. `Project:Zed`는 `project:Zed`로
저장되므로 서로 다른 프로젝트 값이 조용히 합쳐지지 않습니다. 네임스페이스는
소문자 ASCII `[a-z][a-z0-9_-]*`, 값은 비어 있지 않고 제어 문자가 없어야
합니다.

`labels` 필드는 사용자가 소유합니다. `[]`(명시적 빈 필드)도 소유된 값이며,
`labels=None`(또는 생략)은 기존 라벨을 그대로 유지하되 **필드가 전혀 없을
때만** 결정적 제안을 추가합니다. 명시적 목록을 넘기면 검사된 교체이고, `[]`는
제거입니다. 이미 있는 유효한 수동 라벨은 바이트나 순서를 고치려고 자동으로
다시 쓰지 않습니다.

### 결정적 제안(모델 없음)

제안은 소스 바이트와 INDEX 라우팅 상태에서만 유도되며 공급자 호출이나
네트워크가 없습니다:

- `type`, `zone`, `topic`, `project`, `people`/`person`, `entities`/`entity`
  메타데이터와 타이핑된 위키링크 `[[project:...]]`, `[[person:...]]`,
  `[[entity:...]]`
- 실제 ISO 달력 날짜 — `created`/`updated`/`date`/`dates`와 본문의 ISO 날짜
  언급(`date:YYYY-MM-DD`). 현재 시계는 추론 입력이 아닙니다
- 언어 — 명시적 `language`/`lang`이 우선하고, 없으면 제한된 스크립트·어휘
  증거로 보수적으로 감지합니다(한글 → `lang:ko`, 가나 → `lang:ja` 등).
  **라틴 문자 텍스트만으로는 영어라고 추론하지 않으며**, 알 수 없는 라틴
  텍스트에는 `lang:` 라벨이 붙지 않습니다
- `project` 유형 노트는 타이틀/경로에서, `person` 유형 노트는 타이틀/경로에서
  값을 유도합니다
- 경로의 첫 디렉터리 → `zone:`, 해당 경로에 이미 묶인 정확한 INDEX 트리거 →
  `topic:`
- 가져온 파일(import)은 원본 상대 경로 → `source:`, 원본 형식 → `format:`

### CLI: 미리보기·적용·교체·되돌리기

`mnemosyne label`은 라벨 주석을 **기본으로 미리보기만** 합니다. 디렉터리·
잠금·캐시·저널을 만들지 않고, 라벨이 없는 노트에만 제안을 표시합니다.
사용자가 소유한 수동 라벨과 빈 필드는 바뀌지 않습니다. 아래 출력은
`notes/alpha.md`에 타이틀 `Alpha`와 본문만 있는 노트 한 개를 넣은 예입니다:

```bash
mnemosyne --vault my_vault label
```

```json
{"mode": "preview", "ok": true, "notes": 1, "changed": 1, "warnings": [],
 "label_counts": [["zone:notes", 1]],
 "undo_transaction": null}
```

`--apply`는 볼트 잠금을 잡고 계획을 현재 바이트 이미지·라우팅과 다시 대조한
뒤 실제 변경분만 기존 저널로 커밋합니다. 변경이 없으면 아무것도 쓰지 않고 새
트랜잭션도 만들지 않습니다:

```bash
mnemosyne --vault my_vault label --apply
```

```json
{"mode": "applied", "ok": true, "notes": 1, "changed": 1, "warnings": [],
 "label_counts": [["zone:notes", 1]],
 "undo_transaction": "28ba8df945ae48d1b2c094f7d82084ea"}
```

적용은 `labels` 줄만 넣고 다른 모든 바이트(타이틀·본문·빈 줄)를 보존합니다:

```markdown
---
title: Alpha
labels: ["zone:notes"]
---
Body of Alpha.
```

결과의 `undo_transaction`을 기존 공유 저널 실행 취소에 그대로 넘기면 원본
바이트가 정확히 복원됩니다. 라벨 적용은 `handoff fold`와 같은
`Consolidation.undo` 경로를 쓰므로 전용 undo 커맨드가 없습니다. 각 실행의
receipt에 담긴 트랜잭션 ID를 사용하세요:

```bash
mnemosyne --vault my_vault handoff undo --transaction 28ba8df945ae48d1b2c094f7d82084ea
```

```json
{"transaction_id": "28ba8df945ae48d1b2c094f7d82084ea", "state": "undone",
 "journal_path": ".mnemosyne-reviews/28ba8df945ae48d1b2c094f7d82084ea.json"}
```

적용 후 파일이 편집되어 저널의 사후(after) 이미지와 다르면 되돌리기가
거부됩니다. 자동 생성 카탈로그·분할 영수증·보관·관리되는 handoff는 선택에서
제외됩니다. 분할 영수증에 묶인 원본과 토픽 문서도 경로를 직접 지정해도
제외하여 원본 바이트 복원 검증을 유지합니다.

반복된 `--path`로 선택을 제한하고, 반복된 `--label`로 명시적 교체를 제공하며,
`--clear-labels`로 명시적 제거를 요청할 수 있습니다. `--label`과
`--clear-labels`는 상호 배타적입니다(조합하면 종료 코드 2로 아무것도 쓰지
않음). 지정한 경로에 자격 있는 노트가 없으면 경고만 냅니다:

```bash
mnemosyne --vault my_vault label --path notes/alpha.md \
  --label Project:Zed --label Person:Jane
```

```json
{"mode": "preview", "ok": true, "notes": 1, "changed": 1, "warnings": [],
 "label_counts": [["person:Jane", 1], ["project:Zed", 1]],
 "undo_transaction": null}
```

`--clear-labels`를 적용하면 라벨 필드가 `[]`로 바뀌고, 되돌리면 수동 라벨이
바이트 단위로 돌아옵니다.

### init --import: 외부 파일·디렉터리 가져오기

`init --import`는 볼트 밖의 `.md`/`.txt`/`.json` 파일 하나 또는 디렉터리를
가져옵니다. 숨김 파일, `_archive`, 다른 확장자는 제외됩니다. 미리보기 후
`--apply`로 적용하고, `--group-by-label`은 옵트인입니다:

```bash
mnemosyne --vault my_vault init --import ./markdown_export
mnemosyne --vault my_vault init --import ./markdown_export --apply \
  --group-by-label project
```

- **Markdown**은 원본 바이트를 유지한 채 누락된 프론트매터 필드만 추가합니다.
  라벨 필드가 없는 완전한 Markdown도 같은 방식으로 라벨을 얻습니다.
- **`.txt`/`.json`**은 원본 바이트를 그대로 백틱 펜스 안에 넣은 **무손실
  후보**로 변환됩니다. 펜스는 소스에서 가장 긴 백틱 run보다 길어 닫히지
  않고, 원본 확장자가 이름에 남아(`export.txt` → `export.txt.md`) 형식끼리
  덮어쓰지 않습니다.
- 형식이 잘못된 JSON은 추출·재작성 없이 텍스트로 보존하고 `invalid JSON
  retained as text` 경고를 냅니다.
- 잘못된 UTF-8, 심볼릭 링크·리파스 포인트, 변환 이름·유니코드 케이스 폴딩
  충돌은 계획이 만들어지기 **전에** 거부됩니다.
- **원본 파일은 절대 수정하지 않습니다**(원본 다이제스트와 변환 후보
  다이제스트는 분리). 적용 후 복사본의 라벨 외 바이트를 주인이 편집했다면
  재실행이 `import destination changed`로 거부하고 원본·편집본 모두 그대로
  둡니다. 라벨만 편집한 경우에는 그 라벨을 유지합니다. 변경 없는 재실행은
  새 저널을 만들지 않습니다.
- 가져온 노트에는 원본 상대 경로 → `source:`, 원본 형식 → `format:` 라벨이
  붙습니다. 이미 라벨 필드가 있는 Markdown은 수동 라벨을 그대로 유지합니다.
- `--group-by-label <네임스페이스>`는 해당 네임스페이스의 결정적 기존
  값(사전순 첫 값)으로 주제 그룹을 묶고, 없으면 기존 토픽을 씁니다. 기본
  라우팅 동작은 변하지 않습니다.

리포트의 `label_counts`는 노트별 정규화 라벨 히스토그램입니다. 노트당 한 번씩
세고 값의 대소문자를 보존합니다. 아래는 **미리보기 리포트에서 일부 필드만
발췌한 출력**입니다. 앞의 `notes/alpha.md`와 내보낸 파일 세 개를 사용합니다:
타이틀 `Infra`·유형 `project`인 `x.md`, 일반 텍스트 `notes.txt`,
`{"project": "Infra"}`를 담은 `data.json`. 전체 CLI 리포트에는 원본 해시,
라우트, 변경 계획, 검증 상태도 포함됩니다:
아래의 `<digest>`는 실제 64자리 가져오기 다이제스트를 줄여 쓴 것입니다.

```json
{"mode": "preview", "ok": true, "notes": 4, "imports": 3, "topics": 3,
 "warning_count": 0, "warnings": [],
 "label_counts": [["format:json", 1], ["format:md", 1], ["format:txt", 1],
   ["project:Infra", 1], ["source:data.json", 1], ["source:notes.txt", 1],
   ["source:x.md", 1], ["type:project", 1], ["type:topic", 3],
   ["zone:imports/init-<digest>", 3], ["zone:notes", 1]],
 "undo_transaction": null}
```

`undo_transaction`은 프론트매터 정규화 변경만 되돌립니다. 가져온 복사본·주제
목차·INDEX 라우트는 부가적(additive)이라 되돌린 뒤에도 남습니다.

### 검색·MCP: AND 자격 필터, 순위는 불변

```python
from birkin_mnemosyne import Mnemosyne, VaultMemory

mem = VaultMemory({"vault_path": "my_vault"})
mem.write_note(
    "Ingress DNS",
    "nginx ingress resolves service DNS; allow HTTPS through the firewall.",
    zone="devops", labels=["project:Infra", "lang:en"],
)
for hit in mem.search("ingress dns", labels=["project:Infra"]):
    print(hit["title"], hit["labels"])
# ingress-dns ['lang:en', 'project:Infra']

mem.write_note("Deploy runbook", "It rolls out the ingress.", zone="devops")
recall = Mnemosyne("my_vault")
recall.refresh()
print([h["slug"] for h in recall.search("deploy runbook", labels=["zone:devops"])])
# ['deploy-runbook']
```

- `Mnemosyne.search`와 `Memory.search`의 `labels`는 **AND** 의미입니다: 저장된
  라벨이 요청 라벨을 모두 가진 노트만 후보가 되며, 후보 컷·페이지네이션
  **이전**에 적용됩니다. `None`/빈 목록은 필터가 없어 점수·순서가 그대로
  유지됩니다. 검색 결과 hit는 저장된 라벨을 담고, 잘못된 요청은 조회 전에
  `LabelError`로 거부되며 언필터드 검색으로 넓혀지지 않습니다.
- 형식이 잘못된 온디스크 라벨 메타데이터는 그 노트를 "라벨 없음"으로
  인덱싱할 뿐 일반 회상이나 매칭을 깨지 않습니다.

MCP에서 같은 필터가 도구 인자로 노출됩니다. `memory_search`의 `labels`는
생략하거나 `[]`로 주면 필터 없음입니다:

```json
{
  "name": "memory_search",
  "arguments": {"query": "ingress dns", "labels": ["project:Infra"]}
}
```

`memory_remember`의 `labels`는 `None`/생략이면 유지 또는 부재 시 추론, `[]`면
명시적 제거입니다. 아래 생성 예제는 아직 없는 타이틀에 사용합니다:

```json
{
  "name": "memory_remember",
  "arguments": {
    "title": "Ingress DNS",
    "body": "nginx ingress resolves service DNS.",
    "labels": ["project:Infra", "lang:en"]
  }
}
```

`memory_list`는 노트를 나열하되 `labels` 필터를 페이지네이션 **전에** 적용하고,
반환 페이지가 아니라 **전체 자격 노트**의 `label_counts`를 함께 돌려줍니다.
그래서 라벨만으로 노트를 훑어볼 수 있습니다:

```json
{
  "name": "memory_list",
  "arguments": {"zone": "devops", "labels": ["project:Infra"]}
}
```

일반 검색은 모든 깊이의 공개 Markdown을 재귀적으로 인덱스하며,
`init --import`가 만든 중첩 복사본(`imports/init-<digest>/...`)도 포함합니다.
INDEX 라우트는 정확한 상대 경로와 그룹 카탈로그를 유지합니다. 새로 추론한
`zone:` 라벨은 전체 부모 경로를 사용하며 기존 수동 라벨은 유지합니다.

### Hermes에서

현재 소스에는 `birkin_memory_forget`과 `birkin_memory_restore`가 추가되어 있습니다.
아직 출시 전이며 고정된 v0.8.0 제공자와 코어에는 없습니다. 두 도구 모두 기본값은
미리보기이고, 파일을 옮기려면 `confirm=true`가 필요합니다. Forget은 코어의 보호
규칙을 거쳐 삭제 대신 보관하며, restore의 기본 복원 위치는 inbox입니다.
[테스트 노트 정리법](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/integrations/hermes/README.md#cleaning-up-test-notes)에서
정확한 노트 지정, 거부 조건과 복원을 확인할 수 있습니다.
[감쇠 설명](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/integrations/hermes/README.md#decay-changes-ranking-not-storage)처럼
사용하지 않는 테스트 노트는 검색 순위가 낮아져도 디스크에서 사라지지 않습니다.

Hermes 제공자의 `birkin_memory_search`에도 선택적 `labels` 배열이 있습니다.
AND 필터이며 `null`이나 `[]`는 필터를 켜지 않습니다. 설치·활성화·라이프사이클
지침은 [통합 Hermes README](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/integrations/hermes/README.md)의
기존 0.7.0 안내를 그대로 따릅니다:

```json
{
  "name": "birkin_memory_search",
  "arguments": {"query": "ingress dns", "limit": 8, "labels": ["zone:devops"]}
}
```

### 컨텍스트 비용(측정된 fixture)

등록된 프로젝트 노트 하나와 기존 범위 handoff가 있는 전체 시작 JSON fixture에서
라벨 컨텍스트 비용은 UTF-8 **4,207 → 4,303바이트**, 추정 토큰
**1,052 → 1,076(+24)**입니다. `ceil(bytes / 4)` 추정치로 모델 토크나이저
수치가 아니며, 다른 fixture의 handoff 측정(+756)과 합산할 수 없습니다. 라벨은
순위 용어가 되지 않는다는 불변 의미가 이 비용과 별개로 유지됩니다.

공개 고정 벤치마크에서는 노트 160·1,000·10,000개와 검색 엔진 4종의
12개 실행군마다 질문 1,440개를 비교했습니다. 작성자 3명·언어 6개의 모든
순위와 종류·언어·작성자별 5개 지표군이 라벨 적용 전후 정확히 같았고,
원본 시험 자료의 해시도 같았습니다. 이는 이 고정 자료의 회귀 검증이며,
임의의 개인 문서에서 회수율을 보장하는 수치는 아닙니다.

## 프로젝트·태스크별 세션 기억 (0.7.0)

모델이나 API 키 없이 진행한 일, 결정, 열린 작업·질문, 다음 단계와 링크를
저장합니다. 각 기록은 정확한 `project_key`와 선택적 `task_key` 조합에 속하며
덮어쓰지 않습니다. 키는 대소문자·유니코드·슬래시 표기를 그대로 보존하며,
Windows 모양의 키도 파일 경로가 아닌 데이터로 취급합니다.
같은 내용과 `capture_id`로 재시도하면 원래 기록을 돌려줍니다.
내용이 달라진 체크포인트에는 새 ID를 사용하세요.

```bash
export MNEMOSYNE_PROJECT_KEY='example/project'
export MNEMOSYNE_TASK_KEY='release'
mnemosyne --vault my_vault handoff capture \
  --capture-id 'cli-session-1:checkpoint-1' \
  --work 'Packaging is ready; release checks remain.' \
  --decision 'Keep the original notes.' \
  --open-item 'Run Windows CI.' \
  --open-question 'Is the final review approved?' \
  --next-step 'Run the remaining checks.' \
  --link 'https://example.invalid/release'
mnemosyne --vault my_vault handoff latest
mnemosyne --vault my_vault handoff resume
mnemosyne --vault my_vault handoff fold --keep 3
```

초기 설정에서 세션 기억을 켜려면 먼저 미리 보고 명시적으로 적용하세요.

```bash
mnemosyne --vault my_vault init --enable-handoff
mnemosyne --vault my_vault init --enable-handoff --apply
```

미리보기는 파일을 쓰지 않고 요청한 상태와 현재 활성화 상태를 보고합니다.
캡처도 handoff와 없는 INDEX를 활성화하며 기존 경로·예산을 보존합니다.
`--json-stdin`에는 같은 구조의 `work`, `next_step`, `decisions`, `open_items`,
`open_questions`, `links`, `project_key`, `task_key`, `capture_id`와 선택적
`event`, `session_id`, `source`를 넣을 수 있습니다. 목록 필드는 배열입니다.
stdin과 개별 필드 플래그 중 하나를 사용하세요. 종료 코드는 성공 0,
최신 기록 없음 1, 잘못된 입력 2입니다. `--project-key`를 명시하면
`--task-key`도 함께 지정한 경우에만 그 태스크를 선택하며, 환경의 기본
태스크를 다른 프로젝트에 물려주지 않습니다.

```python
from birkin_mnemosyne import HandoffFields, HandoffScope, HandoffStore, StartupReader

scope = HandoffScope("example/project", "release")
receipt = HandoffStore("my_vault").capture(
    scope, HandoffFields("Reviewing the release.", next_step="Check the final head."),
    capture_id="api-session-1:checkpoint-1",
)
reader = StartupReader("my_vault")
bundle = reader.read([], project_key=scope.project_key, task_key=scope.task_key)
assert reader.verify(
    bundle.context, [], project_key=scope.project_key, task_key=scope.task_key,
).complete
print(receipt.path, bundle.estimated_tokens)
```

시작 읽기는 최신 활성 기록 전체, INDEX 전체, 선택한 범위를 검증하는 영수증을
함께 반환합니다. 필요한 상태가 없거나 손상되면 읽기가 실패하며, 경고 예산을
넘었다고 자르지 않습니다. `task_key`는 기록의 범위를 선택하고, 별도 `task`
인자는 INDEX 경로를 어휘로 매칭합니다. 관리되는 handoff 파일은 일반 메모
검색에 섞이지 않습니다.

선택적 [Hermes 제공자](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/integrations/hermes/README.md#session-handoffs)는 활성화되고
프로젝트가 지정된 상태에서 실제 세션 종료·압축 전 콜백으로 저장합니다.
모델 없이 마지막 사용자·어시스턴트 텍스트와 명시적 항목을 보존합니다.
범위가 지정된 prefetch는 빈 질문이나 매칭 없는 질문에도 최신 기록과 INDEX를
완전히 포함합니다. 다른 호스트에서는 아래의 API·CLI·MCP를 명시적으로 호출합니다.

omo, Claude Code 등 MCP 클라이언트에서는 세션 종료 또는 압축 전의 선택한
시점에 `memory_handoff_capture`를 호출하고, 재개할 때 같은 키로
`memory_startup_read`를 호출하세요. INDEX와 handoff가 시작 자료를 제공하면
`paths`는 생략해도 됩니다. 이 호출 시점은 클라이언트가 관리합니다.
다음은 `tools/call`에 넘기는 매개변수 예입니다.

```json
{
  "name": "memory_handoff_capture",
  "arguments": {
    "project_key": "example/project",
    "task_key": "release",
    "capture_id": "mcp-session-1:checkpoint-1",
    "work": "Reviewing the release.",
    "next_step": "Check the final head."
  }
}
```

`memory_handoff_read`는 최신 필드·활성 기록 수·경고를 반환합니다.
`memory_handoff_fold`의 기본 동작은 미리보기입니다. 기본적으로 최신 캡처
3개와 현재 최신 기록을 보존하고, 기존 큐레이션 게이트의 보호 규칙과 전체
볼트 기준 보관 상한을 따릅니다. 비어 있지 않은 미리보기의 `plan_id`를
`handoff fold --apply --plan-id` 또는 MCP `apply=true`에 넘겨 적용합니다.
원본은 해당 범위의 `archive/`에 남고 승인된 입력만 날짜가 있는 요약에 들어갑니다.
결과의 `transaction_id`를 `handoff undo --transaction` 또는
`memory_review_undo(confirm=true)`에 넘기면 원래 바이트로 복원합니다.
사후 이미지가 바뀌면 되돌리기를 거부하며, 되돌린 계획은 새로 미리 봐야 합니다.

Python에서는 `birkin_mnemosyne.handoff_retention`의 `HandoffRetention`이
`preview(scope, keep=3)`와 `apply(scope, plan_id, keep=3)`를 제공합니다.
복원은 기존 `Consolidation.undo(transaction_id)`를 사용합니다.
백업할 때 `.mnemosyne-handoffs/`와 `.mnemosyne-reviews/`를 보존하세요.
일반 메모 수정이나 init 정규화는 이 불변 기록들을 다시 쓰지 않습니다.

기록별 경고 예산은 기본 2,000 추정 토큰이며
`HandoffStore(vault).enable(max_tokens=...)`으로 조정합니다.
완전한 기록·요약은 1 MiB 이내여야 하고, 시작 읽기는 기존의 파일 64개·소스
합계 2 MiB 상한을 지킵니다. 요약이 너무 크면 보관 작업 전에 실패합니다.

**측정 예:** 여섯 필드를 담은 Windows 모양 키의 CLI 시험에서, 완전한 시작
문맥은 UTF-8 650 바이트에서 3,675 바이트로 늘었습니다.
**163 -> 919 추정 토큰(+756)**이며, 빈 범위의 영수증 비용 140도 포함합니다.
원본 handoff만 세면 194입니다. `ceil(bytes / 4)` 추정치로, 모델 토크나이저
수치나 아래의 별도 검색 측정과는 다릅니다. 기록 내용에 따라 비용은 달라집니다.

## 수치가 말해 주는 것

아래 모든 검색 품질은 [RESULTS.md](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#latest-main-replay-2026-10-11)에서
**2026-10-11**, main `876ad40`에서 재실행한 **최종 고정 테스트 분할**입니다.
플랫폼은 Linux x86_64/WSL2, Python 3.14.4입니다. 합성 말뭉치는 6개 언어의 골드
노트 160개이며, 1,000개와 10,000개 노트는 지어낸 방해 노트로 채웠습니다.
**세 명의 독립 질문 작성자**(claude-opus-5.5, gpt-6.1-sol, claude-fable-5.1)가
정확, 저중복 패러프레이즈, 코드 스위칭 질문을 제공합니다. 교차 언어 형제
노트는 채점 전에 제거하고, 튜닝은 dev만 사용합니다.

MRR은 올바른 노트가 얼마나 빨리 나타나는지, R@5는 처음 다섯 개의 결과 안에
들어 있는지를 나타냅니다. 높을수록 좋습니다. 각 화살표는 **기본 코어에서
선택적 의미 모드로**의 이동이며, 이전 초안 결과가 아닙니다. 굵은 값은 손실을
표시합니다. 언어 코드: en 영어, ko 한국어, ja 일본어, zh 중국어, es 스페인어,
de 독일어.

### 언어별, 모든 질문 유형

#### 160개 노트

| 언어 | MRR: 코어 -> 의미 | R@5: 코어 -> 의미 |
|---|---|---|
| en | 0.591 -> 0.640 | 0.698 -> 0.746 |
| ko | 0.578 -> 0.640 | 0.654 -> 0.728 |
| ja | 0.794 -> 0.843 | 0.848 -> 0.899 |
| zh | 0.818 -> 0.871 | 0.867 -> 0.926 |
| es | 0.698 -> 0.744 | 0.769 -> 0.861 |
| de | 0.690 -> 0.749 | 0.763 -> 0.822 |

#### 1,000개 노트

| 언어 | MRR: 코어 -> 의미 | R@5: 코어 -> 의미 |
|---|---|---|
| en | 0.581 -> 0.620 | 0.679 -> 0.714 |
| ko | 0.552 -> 0.614 | 0.613 -> 0.683 |
| ja | 0.782 -> 0.809 | 0.848 -> 0.909 |
| zh | 0.766 -> 0.823 | 0.830 -> 0.881 |
| es | 0.655 -> 0.686 | 0.694 -> 0.713 |
| de | 0.667 -> 0.709 | 0.748 -> 0.778 |

#### 10,000개 노트

| 언어 | MRR: 코어 -> 의미 | R@5: 코어 -> 의미 |
|---|---|---|
| en | 0.568 -> 0.604 | 0.655 -> 0.675 |
| ko | 0.557 -> 0.608 | 0.609 -> 0.658 |
| ja | 0.782 -> 0.816 | 0.848 -> 0.879 |
| zh | 0.764 -> 0.782 | **0.822 -> 0.815** |
| es | 0.673 -> 0.681 | 0.704 -> 0.704 |
| de | 0.683 -> 0.708 | 0.741 -> 0.748 |

### 독립 질문 작성자·언어별

이 MRR 표는 작성자와 말뭉치 크기를 모두 분리해 유지합니다. 의미 모드는
claude-opus-5.5의 스페인어 MRR이 1,000개·10,000개 노트에서, gpt-6.1-sol의
중국어 MRR이 10,000개 노트에서 손실됩니다. 그 셀은 굵게 표시되며 평균으로
흐려지지 않습니다.

#### claude-opus-5.5

| 노트 수 | 언어 | 코어 MRR | 의미 MRR |
|---|---|---|---|
| 160 | en | 0.606 | 0.672 |
| 160 | ko | 0.597 | 0.668 |
| 160 | ja | 0.773 | 0.812 |
| 160 | zh | 0.820 | 0.852 |
| 160 | es | 0.692 | 0.707 |
| 160 | de | 0.694 | 0.739 |
| 1000 | en | 0.592 | 0.644 |
| 1000 | ko | 0.565 | 0.622 |
| 1000 | ja | 0.784 | 0.795 |
| 1000 | zh | 0.750 | 0.794 |
| 1000 | es | 0.653 | **0.646** |
| 1000 | de | 0.672 | 0.692 |
| 10000 | en | 0.588 | 0.639 |
| 10000 | ko | 0.570 | 0.608 |
| 10000 | ja | 0.763 | 0.828 |
| 10000 | zh | 0.746 | 0.764 |
| 10000 | es | 0.653 | **0.639** |
| 10000 | de | 0.672 | 0.687 |

#### gpt-6.1-sol

| 노트 수 | 언어 | 코어 MRR | 의미 MRR |
|---|---|---|---|
| 160 | en | 0.524 | 0.559 |
| 160 | ko | 0.607 | 0.671 |
| 160 | ja | 0.827 | 0.840 |
| 160 | zh | 0.811 | 0.877 |
| 160 | es | 0.628 | 0.711 |
| 160 | de | 0.615 | 0.663 |
| 1000 | en | 0.512 | 0.542 |
| 1000 | ko | 0.605 | 0.674 |
| 1000 | ja | 0.821 | 0.851 |
| 1000 | zh | 0.762 | 0.847 |
| 1000 | es | 0.577 | 0.652 |
| 1000 | de | 0.599 | 0.629 |
| 10000 | en | 0.496 | 0.517 |
| 10000 | ko | 0.609 | 0.668 |
| 10000 | ja | 0.826 | 0.828 |
| 10000 | zh | 0.777 | **0.776** |
| 10000 | es | 0.609 | 0.643 |
| 10000 | de | 0.626 | 0.648 |

#### claude-fable-5.1

| 노트 수 | 언어 | 코어 MRR | 의미 MRR |
|---|---|---|---|
| 160 | en | 0.643 | 0.691 |
| 160 | ko | 0.529 | 0.581 |
| 160 | ja | 0.781 | 0.876 |
| 160 | zh | 0.822 | 0.884 |
| 160 | es | 0.775 | 0.814 |
| 160 | de | 0.762 | 0.844 |
| 1000 | en | 0.641 | 0.673 |
| 1000 | ko | 0.485 | 0.548 |
| 1000 | ja | 0.742 | 0.781 |
| 1000 | zh | 0.785 | 0.829 |
| 1000 | es | 0.736 | 0.761 |
| 1000 | de | 0.729 | 0.804 |
| 10000 | en | 0.621 | 0.655 |
| 10000 | ko | 0.492 | 0.547 |
| 10000 | ja | 0.759 | 0.790 |
| 10000 | zh | 0.770 | 0.807 |
| 10000 | es | 0.756 | 0.763 |
| 10000 | de | 0.751 | 0.788 |

10,000개 노트에서 중국어 작성자별 R@5 손실도 명시적으로 표시됩니다:

| 작성자 | R@5: 코어 -> 의미 |
|---|---|
| claude-fable-5.1 | **0.867 -> 0.844** |
| gpt-6.1-sol | **0.822 -> 0.800** |

### 의미 모드가 코어보다 낮아지는 지점

**이 모드는 옵트인이지 권장 기본값이 아닙니다.** 기준은 "코어보다 낮은 슬라이스가
없어야 한다"였습니다. 테스트 분할에서 풀링된 슬라이스 1개, 작성자 슬라이스
3개, 언어 x 질문 유형 셀 6개에서 이 기준을 넘지 못합니다. 풀링된 중국어와
작성자 손실은 위에 있고, 모든 언어 x 유형 손실은 아래에 있습니다. `mixed`는
코드 스위칭, `para`는 저중복 패러프레이즈를 뜻합니다.

| 노트 수 | 언어 / 유형 | MRR: 코어 -> 의미 | R@5: 코어 -> 의미 |
|---|---|---|---|
| 160 | ja / mixed | **0.896 -> 0.886** | 0.970 -> 0.970 |
| 160 | zh / mixed | **0.917 -> 0.905** | **0.978 -> 0.956** |
| 1000 | ja / mixed | **0.865 -> 0.826** | 0.970 -> 0.970 |
| 10000 | ja / mixed | **0.880 -> 0.859** | 0.970 -> 0.970 |
| 10000 | zh / mixed | **0.875 -> 0.860** | 0.911 -> 0.911 |
| 10000 | zh / para | 0.418 -> 0.487 | **0.556 -> 0.533** |

이 구성은 dev 게이트를 통과했고, 이 테스트 실행 전에 고정되었으며 이후 재튜닝하지
않았습니다. 정확한 키워드 쿼리는 어휘 순서를 유지하며, 어떤 말뭉치 크기에서도
정확한 쿼리는 움직이지 않았습니다. 질문이 노트와 다르게 표현되는 경우가
많으면 의미 모드를 켜고, 대부분 키워드 조회라면 끄세요.

### 자원 사용량

**2026-10-11** 최신 main 재실행은 Linux x86_64/WSL2, Python 3.14.4에서
측정했으며 서비스 보장은 아닙니다. 모든 화살표는 **코어 -> 의미 모드**입니다.
설치 크기는 모델 파일을 제외하고 **0.38 MB -> 80.24 MB**입니다. 고정된 원시
모델 파일은 **531.0 MB**, 간결한 모델은 **138.1 MB**, 합계 **669.1 MB**
(십진 MB)입니다. Hugging Face 캐시는 `$HF_HUB_CACHE`, `$HF_HOME/hub`,
`~/.cache/huggingface/hub` 순으로 정해지며, 간결한 파일은
`$MNEMOSYNE_MODEL_CACHE` 또는 `~/.cache/birkin-mnemosyne` 아래에 있습니다.
새 Hugging Face 버전은 모델 폴더 밖에서 blob을 공유할 수 있어 폴더만
삭제해도 그 크기가 회수된다는 보장은 없습니다. 캐시 관리 도구를 사용하세요.
준비된 모델과 벡터 sidecar에 고정 모델 리비전이 기록됩니다.
원래 추가 메모리 예산은 150 MB였지만 이번 인덱싱의 최대 증가량은
**163 MB**로 이 플랫폼에서 예산을 넘었습니다. 모델을 준비한 상태의
가장 느린 의미 모드 시작은 **617 ms**로 이번 실행에서는 원래 1초 목표
안에 들었습니다.

#### 인덱스와 메모리

| 노트 수 | 디스크 인덱스 | RSS: 검색 | RSS: 인덱싱 |
|---|---|---|---|
| 160 | 0.06 MB -> 0.08 MB | 21 -> 59 MB | 22 -> 185 MB |
| 1000 | 0.33 MB -> 0.42 MB | 26 -> 64 MB | 34 -> 196 MB |
| 10000 | 3.22 MB -> 4.03 MB | 81 -> 120 MB | 157 -> 298 MB |

#### 시작과 지연 시간

| 노트 수 | 시작 중앙값(최대) | p50 | p95 |
|---|---|---|---|
| 160 | 53 ms (62) -> 211 ms (260) | 0.1 -> 0.9 ms | 0.2 -> 1.7 ms |
| 1000 | 82 ms (94) -> 234 ms (254) | 0.2 -> 2.8 ms | 0.4 -> 4.1 ms |
| 10000 | 366 ms (395) -> 570 ms (617) | 1.3 -> 25.2 ms | 3.7 -> 33.0 ms |

RSS는 작은 표준 라이브러리 전용 부모가 띄운 별도의 새 검색·인덱싱
프로세스의 최대 상주 메모리입니다. 시작 시간은 인터프리터 시작, import,
인덱스 로드, 첫 쿼리를 포함하며 셀마다 10개 프로세스를 측정했습니다.
워밍된 지연 시간은 고정 테스트 질문의 처음 300개를 사용했고 인덱스 크기는
그 실행 후 측정했습니다. dev·test를 합산하는 품질 실행의 지연 시간과는
별도 측정입니다. Linux에서는 품질 실행기의 RSS가 부모의 이전 메모리
상한을 물려받을 수 있어 `main_test_run.json`의 RSS·시간 필드는
**기준값이 아닙니다**. `main_footprint.json`과 RESULTS.md를 사용하세요.
지연 시간은 볼트 크기와 머신 부하에 따라 늘어나며, 과거 macOS 실행과는
플랫폼과 방법이 다릅니다.

## 솔직한 한계

- **이전 토크나이저 실험은 한국어 검색 개선을 입증하지 못했습니다.** 10,000개 노트에서
  이전 macOS 토크나이저 실행은 MRR **0.569**, 최신 Linux 코어 재실행은
  **0.557**입니다. 별도 측정이며 플랫폼 차이를 분리한 비교는 아닙니다. 영어 어간은 코드
  스위칭 한국어 질문에서 영어 방해 노트와도 매칭됩니다. 한국어 토크나이제이션
  자체는 변하지 않았습니다. 어간 재가중치는 영어와 한국어를 맞바꿨고,
  소수 스크립트 부스트는 독립적으로 작성된 반대 질문에 손해를 줬습니다.
  둘 다 출시하지 않았습니다: [코어의 코드 스위칭 질문](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#code-switched-queries-in-the-core-measured-not-changed) 참고.
- **이것은 합성 개인 규모 벤치마크입니다.** 다른 메모리 프로젝트보다 우월함,
  답변 정확도, 보편적 다국어 커버리지를 입증하지 않습니다. 저중복
  패러프레이즈는 어휘 코어에게 여전히 어렵습니다. 데바나가리, 태국어처럼
  결합 모음 부호가 있는 스크립트는 현재 토크나이저가 그 부호에서 분할합니다.
- **쿼리 확장은 작성자만큼만 좋습니다.** 확장 수치는 모델이 쓴 질문과 모델이
  쓴 확장에서 나왔습니다. 작성자 둘 중 하나는 스페인어와 독일어 노트에 대한
  코드 스위칭 질문에서 영어와 한국어로 답해 코어보다 약 0.05 MRR 낮았습니다.
  넓힌 검색 한 번은 호스트에게 출력 토큰 약 115~200개와 약 2배의 순위화
  시간이 듭니다.
- **의미 결과가 무관할 수 있습니다.** 모드를 켜면 어휘 매칭이 없는 쿼리에도
  의미 후보가 반환되며 관련성 하한이 없습니다. 토크나이저 동등성은 이
  벤치마크에서만 확인했고, 다양한 CJK 텍스트가 있는 장수명 프로세스의 메모리는
  측정하지 않았습니다. 최신 자원 측정은 Linux x86_64/WSL2만 다루며, 과거 측정은 macOS arm64입니다.
- **압축에는 쓰기 비용이 있습니다.** 저장할 때 인덱스 전체를 다시 압축하며,
  로드할 때 압축된 텍스트와 디코딩된 텍스트를 잠시 함께 들고 있습니다. 한
  볼트에 여러 버전의 라이브러리를 섞어 쓰면 캐시를 반복해서 다시 만듭니다.
  단일 노트 변경 후 인덱스 캐시 쓰기는 합쳐집니다(2초에 최대 한 번, 종료 시
  flush 한 번). 크래시 후에는 다음 refresh에서 노트 파일로 캐시를 다시
  만듭니다.
- **큐레이션 안전성은 정확성보다 좁습니다.** 실행기는 파일 작업 범위를
  제한합니다. 모델 선택은 여전히 배치와 연결 품질에 영향을 줍니다. Python의
  명시적 `purge_expired()` 유지보수 호출은 만료된 노트를 삭제할 수 있으며 MCP로
  노출되지 않습니다.
- 이전 LongMemEval 검색과 엔드투엔드 QA 하네스는 이 저장소에서 **아직 공개되지
  않았습니다**. 그 수치는 여기서 생략합니다. 동반 논문은 커밋된 재현 하네스를
  대신하지 않습니다.

## 벤치마크 재현

코어(선택 런타임 의존성 없음):

```bash
python benchmarks/retrieval/bench_retrieval.py --sizes 160 1000 10000 --install-size
```

`--install-size`는 네트워크가 필요합니다. 패키지를 새 가상 환경(`uv`가 PATH에
있으면 uv, 아니면 pip)에 빌드·설치해 설치 용량을 측정합니다. 오프라인에서는
같은 벤치마크를 옵션 없이 실행하세요:

```bash
python benchmarks/retrieval/bench_retrieval.py --sizes 160 1000 10000
```

검색 시점 쿼리 확장은 두 작성자의 커밋된 확장을 재생합니다(모델 호출 없음,
선택 의존성 없음):

```bash
python benchmarks/retrieval/bench_retrieval.py --engines bm25 expanded-claude expanded-gpt --sizes 160 1000 10000 --json run.json
python benchmarks/retrieval/compare.py run.json run.json --engine-before bm25 --engine-after expanded-claude
```

의미 모드는 쿼리 시점에 트랜스포머 없이 `minishlab/potion-multilingual-128M`
정적 임베딩을 사용합니다. 엑스트라를 설치하고 모델을 한 번 명시적으로
준비하세요:

```bash
pip install "birkin-mnemosyne[semantic]"
python -m birkin_mnemosyne.semantic
```

`Mnemosyne(vault, semantic=True)` 또는 `MNEMOSYNE_SEMANTIC=1`로 옵트인합니다.
검색은 절대 모델을 다운로드하거나 변환하지 않습니다. 엑스트라가 없거나 모델이
준비되지 않았는데 요청하면 검색은 코어 순위를 사용하고 이유 한 줄을 로그로
남깁니다. 의미 청크는 어휘 순위와 융합됩니다. 완전한 어휘 매칭이 먼저 오고,
동률 융합은 어휘 순위를 사용합니다.

모델을 준비한 체크아웃 상태에서:

```bash
python benchmarks/retrieval/bench_retrieval.py --engines bm25 hybrid --sizes 160 1000 10000 --json run.json --install-size --install-extras semantic
python benchmarks/retrieval/compare.py run.json run.json --engine-before bm25 --engine-after hybrid
```

커밋된 품질 실행은 [main_test_run.json](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/main_test_run.json)입니다.
별도로 측정한 기준 자원 값은
[main_footprint.json](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/main_footprint.json)입니다:

```bash
python benchmarks/retrieval/measure_footprint.py --output footprint-main.json
```
전체 질문 유형 표, 질문 수, 거부된 아이디어, 설치 용량 방법론은 RESULTS.md를
참고하세요. 추가 점검과 오프라인 예제:

```bash
pytest -q                                # MCP·의미·정적 모델 스위트는
                                         # [mcp] / [semantic] 없으면 건너뜀. 이름이 출력에 표시됨
python examples/quickstart.py            # 쓰기, 검색, 감쇠
python examples/automatic_profiles.py    # 프로필 리뷰와 영속화
python benchmarks/bench_safety_matrix.py # 방어 계층 절제(ablation)
python benchmarks/bench_korean_embed.py  # 임베딩 베이스라인; [bench] 필요
```

## CurationPlan/1: 어떤 모델로든 범위가 제한된 큐레이션

모델이 타입이 있는 JSON 작업(rezone, link, supersede, archive)을 제안하면,
결정적 실행기가 검증, 클램프(clamp), 적용, 감사를 수행합니다. 큐레이션
스키마에는 삭제 작업이 없습니다. archive는 노트를 옮길 뿐입니다. 아카이브는
활성 노트의 `ARCHIVE_CAP_MIN`과 `ARCHIVE_CAP_FRACTION`으로 회차당 상한이 있고,
부정 극성 경고와 제어 노트는 보호됩니다. 모든 이동은 볼트 안에 머물고,
`_archive`는 활성 영역이 아니며, 자유 텍스트 요약은 제어 신호가 아니라 무해한
데이터입니다. 파싱할 수 없는 출력은 빈 계획이 됩니다. 배치는 모델 판단이고,
함께 배치된 노트를 연결하는 것은 기계적입니다. 스키마 검증만으로는 대량
아카이빙을 막지 못합니다. 실행기의 클램프가 호출마다 상한을 두므로 반복 호출은
더 많이 아카이브할 수 있습니다(아카이브는 되돌릴 수 있음). 경로 포함과 슬러그
조회가 하위 레벨 파일 작업도 보호합니다.

```python
from pathlib import Path

from birkin_mnemosyne import Mnemosyne, run_curation_pass, get_completer

vault = Path("my_vault")
mem = Mnemosyne(vault)
mem.refresh()
hits = mem.search("kubernetes ingress dns")

# 볼트 인자는 pathlib.Path여야 합니다
outcome = run_curation_pass(vault, get_completer("codex"), provider="codex")
# 또는 직접 만든 complete(prompt: str) -> str 콜러블을 넘기세요.
```

openclaw, hermes 또는 자신의 루프에서 `mem.search(query)`를 회상 도구로
노출하고, 실제로 쓴 노트에는 `mem.record_access(note_slug)`를 호출한 뒤, 기존
모델 클라이언트를 `run_curation_pass(vault_path, my_complete,
provider="custom")`에 넘기세요. 수락/거부된 작업, 아카이브 상한, 감사 요약이
담긴 `CurationOutcome`을 돌려줍니다. 이미 데이터로 된 계획이 있다면
`evaluate_plan(vault_path, plan)`이 같은 게이트를 드라이 런으로 실행하고,
`apply=True`를 넘기면 적용합니다.

| 공급자 | 호출 | 계획 제약 |
|---|---|---|
| `claude` | `claude -p`, 빈 도구 허용 목록 | 프롬프트 명시 |
| `codex` | `codex exec --sandbox read-only --output-schema` | 강제 JSON 스키마 |
| `api` | 표준 라이브러리 `urllib`로 Anthropic Messages API | 프롬프트 명시 |
| `gemini` | `gemini -p -`, CLI 기본값 | 프롬프트 명시 |
| `local` | `ollama run <model>` | 프롬프트 명시 |

## MCP 서버(Claude Code, Claude Desktop, Codex CLI, Cursor)

볼트를 [Model Context Protocol](https://modelcontextprotocol.io)로 서빙하면
어떤 MCP 클라이언트든 기억, 회상, 큐레이션을 쓸 수 있습니다. 서버는 선택
엑스트라입니다. 코어 라이브러리는 표준 라이브러리만 쓰며, stdio로 한 줄
명령으로 실행합니다:

```bash
uvx --from "birkin-mnemosyne[mcp]" \
    mnemosyne-mcp --vault ~/mnemosyne
```

(또는 `pip install "birkin-mnemosyne[mcp]"` 후 `mnemosyne-mcp` 실행). 첫
실행이 SDK를 다운로드합니다. 클라이언트가 그 첫 시작에서 타임아웃되면 터미널에서
명령을 한 번 실행해 두세요.

| 설정 | 방법 |
|---|---|
| 볼트 디렉터리 | `--vault PATH`, 아니면 `$MNEMOSYNE_VAULT`, 아니면 `~/.birkin-mnemosyne/vault` |
| 새 노트에 `source` 요구 | `--evidence-required` 또는 `MNEMOSYNE_EVIDENCE_REQUIRED=1` |
| identity/시작 읽기 루트 | `--identity-root PATH`, 아니면 `$MNEMOSYNE_IDENTITY_ROOT`, 아니면 볼트. `memory_identity_read`와 `memory_startup_*`는 이 루트 아래 파일만 읽을 수 있습니다(경로는 여기에 한정). 에이전트가 읽어도 되는 파일만 담긴 디렉터리를 가리키세요 |
| 보호 노트 예산(기본 1000, `0` = 무제한) | `--max-protected-notes N` 또는 `MNEMOSYNE_MAX_PROTECTED_NOTES=N` |
| 활성 노트 바이트 예산(기본 104857600, `0` = 무제한) | `--max-vault-bytes N` 또는 `MNEMOSYNE_MAX_VAULT_BYTES=N` |

**Claude Code**

```bash
claude mcp add --scope user mnemosyne -- \
  uvx --from "birkin-mnemosyne[mcp]" \
  mnemosyne-mcp --vault ~/mnemosyne
```

**Claude Desktop**(`claude_desktop_config.json`)과 **Cursor**(`~/.cursor/mcp.json`
또는 `.cursor/mcp.json`)는 같은 모양을 사용합니다:

```json
{
  "mcpServers": {
    "mnemosyne": {
      "command": "uvx",
      "args": [
        "--from", "birkin-mnemosyne[mcp]",
        "mnemosyne-mcp", "--vault", "~/mnemosyne"
      ]
    }
  }
}
```

**Codex CLI**(`~/.codex/config.toml`, 또는 `codex mcp add mnemosyne -- uvx ...`):

```toml
[mcp_servers.mnemosyne]
command = "uvx"
args = ["--from", "birkin-mnemosyne[mcp]",
        "mnemosyne-mcp", "--vault", "~/mnemosyne"]
```

여러 클라이언트가 같은 `--vault`를 가리키면 메모리를 공유합니다. 쓰기는 잠금
파일로 서버 프로세스 사이에서 직렬화됩니다.

### IDE에서 사용하기

로컬 **stdio MCP**를 지원하는 IDE 에이전트는 같은 저장소를 사용할 수 있습니다.
먼저 별도 가상환경에 `birkin-mnemosyne[mcp]`를 설치하고, IDE가 그 환경의
Python을 실행하도록 설정합니다. VS Code의 `.vscode/mcp.json` 예시:

```json
{
  "servers": {
    "mnemosyne": {
      "type": "stdio",
      "command": "/absolute/path/to/mnemosyne-venv/bin/python",
      "args": ["-m", "birkin_mnemosyne.mcp_server"],
      "env": {"MNEMOSYNE_VAULT": "/absolute/path/to/memory-vault"}
    }
  }
}
```

두 경로를 실제 경로로 바꾸세요. Windows에서는 가상환경의
`Scripts/python.exe`를 사용하며 JSON 경로에 `/`를 써도 됩니다.
공백이 있는 경로도 하나의 JSON 값으로 넣고, 값 안에 셸 따옴표를 추가하지 마세요.
IDE에서 서버를 켜고 도구 사용을 승인해야 합니다.

PyPI 0.6.0과 `876ad40` 시점의 main은 macOS와 Windows에서 공식 MCP SDK로
검색과 완전한 시작 읽기를 확인했습니다. Herdr 안의 실제 omo 에이전트도 두
도구를 호출했습니다. 이것이 모든 IDE에서 직접 실행했다는 뜻은 아닙니다.
Cursor, JetBrains, Zed, Windsurf, Antigravity, Orca와 CLI 에이전트의
[호환성 표·정확한 설정 형식·공식 출처](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/ide-compatibility.md)를 참고하세요.
여기서 Orca는 [Orca IDE](https://www.onorca.dev/docs)를 뜻합니다. 별도 Orca 전용
MCP 파일을 추정하지 않고, 실제 작업 트리에서 실행하는 에이전트의 MCP 설정을 사용합니다.

### 도구

| 도구 | 하는 일 | 안전한 기본값 |
|---|---|---|
| `memory_search` | 스니펫이 있는 BM25 + 감쇠 + 영역 순위 결과. 선택 사항인 `synonyms` / `keywords` / `related` / `note_line`이 쿼리를 넓힘. `labels`(AND) 필터; 생략/`[]` = 필터 없음 | 읽기 전용 |
| `memory_get_note` | `version`이 있는 전체 노트. 사용으로 집계됨 | - |
| `memory_list` | 영역별 노트, 페이지네이션. `labels`(AND) 필터와 전체 자격 노트의 `label_counts` | 읽기 전용 |
| `memory_remember` | 노트 쓰기: `mode="create"` / `"append"` / `"replace"`. `labels`는 None=유지/부재 시 추론, `[]`=제거 | `create`는 절대 덮어쓰지 않음. `replace`는 `expected_version` 필요 |
| `memory_related` | 한 노트의 기계적 링크 후보 | 읽기 전용 |
| `memory_forget` | 큐레이션 게이트를 거쳐 노트를 `_archive`로 이동 | `confirm=true`가 아니면 드라이 런. 절대 삭제하지 않음 |
| `memory_restore` | `_archive`에서 노트를 다시 꺼냄 | - |
| `memory_curation_catalog` | CurationPlan 작성용 구조화 카탈로그 | 읽기 전용 |
| `memory_curate` | 결정적 게이트로 CurationPlan/1 실행 | `apply=true`가 아니면 드라이 런 |
| `memory_review_questions` | 중복·중첩·충돌 가능한 노트 쌍을 사용자에게 질문으로 제시 | 읽기 전용 |
| `memory_review_apply` | 리뷰 질문에 대한 사용자의 명시적 답 하나를 적용(`drop-*`는 노트를 아카이브, `merge`는 승인된 본문을 씀). 원본 바이트 이미지 둘 다 저널링 | `confirm=true`가 아니면 드라이 런 |
| `memory_review_undo` | 모든 사후 이미지가 그대로면 리뷰 트랜잭션의 바이트 정확 원본을 복원 | `confirm=true`가 아니면 드라이 런 |
| `memory_identity_read` | identity 루트 아래 SOUL/AGENTS 스타일 Markdown을 카탈로그, 순위 섹션, 한 섹션, 또는 전체 파일로 읽음 | 읽기 전용 |
| `memory_kibitzer_candidates` | 쿼리에 대한 순위 매겨진 라이브 노트 후보, 짧은 발췌 포함. 아카이브·시스템·만료 노트는 건너뜀 | 읽기 전용 |
| `memory_startup_read` | identity 루트 아래 시작 파일(그들이 MUST READ하는 로컬 파일 포함)을 커버리지 검사와 함께 완전히 읽음 | 읽기 전용 |
| `memory_startup_verify` | 같은 파일을 다시 읽고 반환된 시작 컨텍스트를 그 파일들과 대조 검증 | 읽기 전용 |
| `memory_handoff_capture` | 여섯 필드를 담은 불변 프로젝트·태스크 체크포인트 저장 | 같은 ID·내용의 재시도는 원래 기록 재사용 |
| `memory_handoff_read` | 해당 범위의 최신 기록·활성 수·크기 경고 | 읽기 전용 |
| `memory_handoff_fold` | 큐레이션 게이트를 거친 날짜별 요약·보관, 기존 저널로 복원 | `apply=true`와 새 `plan_id`가 없으면 미리보기 |
| `memory_index_register` | 항상 로드되는 INDEX에 `trigger -> document` 매핑 하나 추가. 추가적이고 멱등적. 제거나 삭제 없음 | 추가적 쓰기 |
| `memory_index_read` | 순위 상한 없이 모든 INDEX 항목 또는 완전한 주제 하나 읽기 | 읽기 전용 |
| `memory_open_trigger` | 정확한 트리거가 가리키는 문서 열기. 없으면 일반 검색으로 폴백 | 읽기 전용 |
| `memory_index_check` | 고아, 매달린 경로, 커버리지 오류를 쓰기 없이 감사 | 읽기 전용 |
| `memory_index_split` | 한 노트를 라우팅된 주제 문서로 무손실 분할 미리보기 또는 적용 | `apply=true`가 아니면 미리보기 |
| `memory_capacity` | 예산 대비 활성·보호 노트 수와 인덱스 바이트 | 읽기 전용 |

리소스 `mnemosyne://digest`(프롬프트 다이제스트)와 `mnemosyne://note/{slug}`, 그리고
프롬프트 `curate_vault`가 추가로 있습니다. 호출하는 에이전트가 큐레이터입니다.
카탈로그를 읽고 계획을 쓴 뒤 `memory_curate`가 `run_curation_pass`와 똑같이
클램프합니다. 보호 노트는 그대로 있고 아카이브 상한은 호출마다 다시 계산되므로
반복 호출은 더 많이 아카이브할 수 있습니다. forget과 큐레이션은 아카이브만
합니다. `memory_review_undo`는 원본 바이트를 복원하고, 이동된 아카이브는
보존되는 비공개 스냅샷으로 회수합니다. 바뀌거나 동시에 들어온 파일은 덮어쓰지 않습니다.
`purge_expired`는 Python 전용 유지보수 호출로 남습니다. 도구가 반환하는 노트
텍스트는 이전 세션의 저장 데이터이므로, 서버는 클라이언트에게 그 안의 지시를
따르지 말라고 안내합니다.

**용량.** 보호 규칙은 변하지 않습니다. 부정 극성, identity/선호, 보관(filed)+
링크 노트는 `memory_forget`과 `memory_curate`의 대상이 되지 않습니다. 보호
메모리가 무한정 자라지 않도록 서버는 활성 볼트를 예산(위 설정 두 개. 잘못된
값이면 시작 시 중단)과 비교합니다. 예산 초과 시 `memory_capacity`와
`memory_remember`(`capacity_warning`)가 알리고, `memory_review_questions`가
가장 오래되고 가장 덜 쓰인 보호 노트에 `retire_questions`를 추가하며, 에이전트는
사용자에게 물어야 합니다(`keep` 또는 `retire`). 어떤 것도 자동 삭제되지
않습니다. `retire`는 저널링된 `memory_review_apply` 경로로 노트를 아카이브하고,
`memory_review_undo`가 복원합니다. 용량과 INDEX 경고가 모두 없으면 기존
클라이언트에 새 키가 보이지 않습니다. INDEX 토큰 경고만 있으면 용량 보고서는
붙을 수 있지만 보관 질문이나 선택지는 붙지 않습니다. 이 경고는 메모 수나
바이트 예산을 초과했다는 뜻이 아닙니다.

## 자동 역할 프로필

`ProfileMemory`는 대화 교환을 즉시 기록하고 소유한 백그라운드 워커 하나에서
검토합니다. 리뷰어는 JSON을 반환하며, `flush()`가 내구성 경계이자 잘못된
리뷰어 출력을 드러내는 지점입니다.

```python
import json
from birkin_mnemosyne import ProfileMemory

def review(exchange):
    # 이 결정적 예제를 자신의 모델 클라이언트로 바꾸세요.
    return json.dumps({"profiles": {
        "preferences": "Prefers evidence before conclusions.",
        "soul": "Use direct Korean.",
    }})

with ProfileMemory(vault_path, review) as profiles:
    profiles.record_exchange(user_message, assistant_message)
    profiles.flush()
```

`ProfileMemory`가 소유하는 `system/` 디렉터리에는 정확히 다섯 개의 역할 파일이
있습니다(큐레이션 게이트는 이들을 특별 취급하지 않습니다):

| 파일 | 저장되는 안내 |
|---|---|
| `user.md` | 사용자 특성과 안정적인 개인 맥락 |
| `preferences.md` | 선호와 자주 고르는 선택 |
| `soul.md` | 대화 스타일과 상호작용 안내 |
| `workflow.md` | 작업 프로세스와 실행 안내 |
| `automation.md` | 워크플로 자동화 안내 |

기본적으로 `ProfileMemory(vault_path, review)`는 그 파일들을 부트스트랩하고
중복 제거된 안내 줄을 추가합니다. `save=callable`을 넘기면 `system/` 디렉터리나
파일을 만들지 않습니다. 검토된 각 교환은 `ProfileProposal` 객체 튜플로 파싱되어
호출자가 소유한 저장소로 전달됩니다. 싱크 모드 인스턴스는 파일을 소유하지 않으므로
`read_profiles()`를 쓸 수 없습니다.

리뷰어 계약은 `profiles` 객체 하나를 담은 JSON 객체입니다. 프로필 키는 위 표의
것이어야 합니다. 값은 공백 정규화 후 `add` 제안이 되는 레거시 비어 있지 않은
문자열이거나, `[{"action":"replace","old_text":"old","content":"new"}]` 같은
순서 있는 제안 목록일 수 있습니다. 작업은 `add`, `replace`, `remove`이며,
잘못된 JSON, 알 수 없는 키/작업, 문자열이 아닌 필드, 필수 텍스트 누락은
`flush()`에서 `ProfileReviewError`를 일으킵니다. `close()`는 새 제출을 막고
워커를 해제합니다. 컨텍스트 매니저는 자동으로 flush하고 닫습니다. 오프라인
엔드투엔드 예제는 `python examples/automatic_profiles.py`를 실행하세요.

## API 목록

```python
from birkin_mnemosyne import (
    Mnemosyne,          # 기계적 인덱스/순위 엔진
    MemoryIndex,        # 옵트인 항상 로드 메모리 INDEX
    StartupReader,      # 검증된 호스트 시작 읽기, 태스크 결합 완전 읽기 포함
    HandoffStore, HandoffScope, HandoffFields,  # 불변 범위별 세션 체크포인트
    VaultMemory,        # write_note / rezone / digest 편의 래퍼
    ProfileMemory,      # 백그라운드 검토 역할 프로필 영속화
    ProfileReviewError, # 잘못된 리뷰어 출력
    run_curation_pass,  # 안전한 큐레이션 드라이버
    evaluate_plan,      # 구조화 계획 게이트(기본 드라이 런)
    get_completer,      # 공급자 레지스트리(claude|codex|api|gemini|local)
    validate_clamp,     # 적용 없이 계획을 검사하고 싶을 때의 게이트
    build_plan_prompt, extract_plan, mechanical_catalog,
    slug, tokenize, bm25_scores,
    KibitzerAdapter,    # Kibitzer 형태 회상; 키가 있으면 recall()이 재정렬
    RecallResult,       # recall() 후보와 선택 방식·대체 이유
    opengateway_decider, translate_views, RerankError,  # 호스팅 재정렬 구성 요소
)
```

주요 `Mnemosyne` 메서드: `refresh()`,
`search(query, limit=8, zone=None, expansions=None, labels=None)`, `related(slug)`,
`record_access(slug)`, `stale()`, `rezone(slug, zone)`, `zone_priorities()`,
`stats()`.

## 볼트 레이아웃과 설정

노트는 슬러그 이름의 Markdown 파일이며 YAML 프론트매터와 `[[wikilinks]]`를
씁니다. 영역은 전체 상대 디렉터리 경로이고, 볼트 루트가 인박스입니다.

```text
my_vault/
  inbox-note.md
  devops/
    ingress-dns.md
  people/
  projects/
    Active Work/
      roadmap.md
  identity/
  knowledge/
  journal/
  system/                       # ProfileMemory가 소유하는 역할 파일
  _archive/                     # 소프트 삭제된 노트
    projects/Active Work/       # 보관 시 원래 부모 경로 유지
  .mnemosyne-memory-index/       # 옵트인; index.json 라우팅과 상주 맥락 맵
  .mnemosyne-handoffs/           # 불변 범위별 기록·요약·아카이브·활성화 설정
  .mnemosyne-index.json.z        # 다시 만들 수 있는 압축 인덱스 캐시
  .mnemosyne-dynamics.json       # 영속 사용 상태
  .mnemosyne-vectors.npz         # 다시 만들 수 있는 의미 벡터 캐시
  .mnemosyne-reviews/            # 리뷰 실행 취소 저널(<transaction-id>.json)
  .mnemosyne-mcp.lock            # 프로세스 간 쓰기 잠금
```

탐색은 기본적으로 재귀적입니다. 숨김 파일·디렉터리(`.git`, `.obsidian` 포함),
`node_modules`, `__pycache__`, 심볼릭 링크와 Windows 리파스 포인트는 따라가지
않습니다. 파일명에서 확장자를 뺀 이름을 계속 노트 키로 사용합니다. 같은 키가
여러 경로에 있으면 수정 시간이 최신인 파일을 선택하고 충돌 경고를 남깁니다.
시간이 같으면 POSIX 상대 경로의 사전순 첫 파일을 선택합니다. INDEX 라우트는
키가 아니라 정확한 경로를 유지합니다.

예를 들어 `zone="projects/Active Work"`는 쓰기와 영역별 검색에서 전체 부모
경로를 지정합니다. 중첩 경로나 사람이 붙인 이름은 표기를 유지하고, 기존의
단순 이름은 계속 정규화합니다(`"Projects"` → `"projects"`). 절대 경로,
드라이브·UNC, 상위 경로 이동, 역슬래시와 숨김·캐시 경로는 거부됩니다.
Windows에서 허용되지 않는 파일명 문자와 구성 요소 끝의 점·공백도 거부됩니다.
쓰기·이동·저널 작업은 연결된 대상 파일이나 부모 폴더도 거부합니다.
Windows 리파스 포인트도 같은 규칙을 따릅니다.

`projects/Active Work/roadmap.md`를 보관하면
`_archive/projects/Active Work/roadmap.md`로 이동합니다. 어느 깊이에 있든
`_archive` 구성 요소는 대소문자와 관계없이 활성 보기에서 제외되며,
`zone="_archive"`로 보관 트리를 검색합니다. MCP `memory_restore`의 기본
목적지는 계속 인박스입니다. 중첩 부모를 고르려면
`zone="projects/Active Work"`를 지정하세요. 저널 되돌리기는 원래 경로와
바이트를 복원하며, 실행 후 파일이 바뀌었다면 거부합니다.

인덱스 캐시, 벡터 파일, 잠금 파일은 Mnemosyne 프로세스가 볼트를 쓰는 동안이
아닐 때만 지워도 안전합니다. 캐시는 자동으로 다시 만들어지고(벡터 파일이 없으면
다음 의미 검색이 볼트 전체를 다시 임베딩), 잠금 파일도 다시 생기지만, 다른
프로세스가 잠금 파일을 들고 있을 때 지우면 Linux와 macOS에서 상호 배제가
깨집니다. 잠금 파일과 벡터 파일은 git과 파일 동기화에서 제외하세요. 백업이나
동기화 시 `.mnemosyne-dynamics.json`(사용 이력)과 `.mnemosyne-reviews/`(리뷰
답변 실행 취소에 필요)를 보관하세요.

`VaultMemory({"vault_path": "my_vault"})`가 볼트를 선택합니다. 레거시 `vault`
구성 키도 받아들여지며, 둘 다 없으면 기본값은 `./vault`입니다. `Mnemosyne`은
경로를 직접 받습니다. 쓸 때 `zone=`을 지정해 배치를 고르고, 그렇지 않으면 노트
유형이 영역에 매핑됩니다:

| 노트 유형 | 기본 영역 |
|---|---|
| `person` | `people` |
| `project` | `projects` |
| `preference` | `identity` |
| `fact`, `topic` | `knowledge` |
| `session` | `journal` |

`_archive`는 활성 큐레이션 영역이 아닙니다. 사용 상태를 버리지 않고 캐시를 다시
만들 수 있으며, 레거시 `.mnemosyne-index.json` 캐시는 다음 저장 때 제거됩니다.
한 볼트에 여러 버전의 라이브러리를 섞어 쓰면 캐시를 반복해서 다시 만듭니다.
MCP 경로와 증거 설정은 [MCP 서버 레퍼런스](#mcp-서버claude-code-claude-desktop-codex-cli-cursor)에 있습니다.

## 업스트림 기여

광훈은 에이전트 하네스와 에이전트 메모리가 한국어를 다루는 방식이 마음에 들지
않아 이 작업을 시작했습니다. 에이전트 팀을 돌려 격차를 조사하고 변경을
테스트한 뒤, 자신의 환경에만 두지 않고 업스트림으로 기여했습니다.
birkin-mnemosyne 검색 작업과 메모리 어댑터의 발견이 아래 프로젝트들의
기여가 되었습니다.

이 표는 `ashmoonori-afk`가 birkin-mnemosyne에서 파생된 **다른 저장소들**에
작성한 기여이며, 소스 링크와 **2026-10-11 KST** 기준 상태를 담고 있습니다.
birkin-mnemosyne 내부 PR과 무관한 하네스 작업은 제외됩니다. 열린 제안은
출시된 개선이 아니며, 승인은 머지를 의미하지 않습니다. 종료된 작업은 명시적으로
표시합니다. 연결된 검색 이득은 합성 벤치마크일 뿐, 실제 대화에 대한 보장이
아닙니다.

| 프로젝트 | 기여 | 상태 | 해당 프로젝트에 어떤 개선인지, 또는 제안 내용 | birkin-mnemosyne 근거와 한국어 관련성 |
|---|---|---|---|---|
| oh-my-openagent | [PR #9209](https://github.com/code-yeongyu/oh-my-openagent/pull/9209) | Merged | 회상이 자동으로 CJK 인지 BM25 또는 하이브리드 순위를 골라 굴절·비분절 쿼리도 부분 문자열 매칭이 놓친 노트를 찾도록 함. 메인테이너 리뷰에서 영어 회상 가드가 추가됨 | 이 PR은 birkin-mnemosyne의 한국어 인지 바이그램 BM25 접근을 명시적으로 인용. 한국어 굴절, 일본어·중국어가 혜택 |
| oh-my-openagent | [PR #9341](https://github.com/code-yeongyu/oh-my-openagent/pull/9341) | Merged | 회상이 한자(한글자)를 하나씩 매칭하고 매칭 발췌를 보여 줘, 중국어·일본어 한자 쿼리가 공유 문자로 노트를 찾도록 함 | birkin-mnemosyne 토크나이저 작업과 벤치마크의 한자 발견을 이식. 한국어 한자도 다루며 일반 한글 동작은 그대로 |
| oh-my-openagent | [PR #9342](https://github.com/code-yeongyu/oh-my-openagent/pull/9342) | Merged | 선택 사항인 가중 동의어·키워드·관련어가 다르게 표현된 노트를 회상이 찾도록 하면서 정확 매칭을 먼저 유지. 기본 꺼짐이고 잘못된 확장은 일반 회상으로 폴백 | birkin-mnemosyne에서 처음 측정된 쿼리 확장을 적용. 한국어 패러프레이즈 이득이 측정됐지만, 확장은 토큰이 들고 일부 혼합 언어 쿼리는 회귀 |
| oh-my-openagent | [PR #9275](https://github.com/code-yeongyu/oh-my-openagent/pull/9275) | Closed; split into #9341 and #9342 | 한자 매칭과 쿼리 확장을 합친 제안이 두 개의 집중된 PR이 되어 각각 머지됨. 이 종료된 PR은 독립 출시되지 않음 | 두 부분 모두 birkin-mnemosyne의 토크나이저·검색 실험에서 파생. 한국어 쿼리 확장 포함 |
| Hermes Agent | [PR #131586](https://github.com/NousResearch/hermes-agent/pull/131586) | Merged | 커뮤니티 카탈로그에 고정된 소스 버전, 로컬 Markdown 저장, Hermes 프로필별 분리 볼트를 갖는 외부 메모리 제공자가 추가됨 | birkin-mnemosyne의 Hermes 어댑터를 카탈로그에 등록. 한국어 전용 코어 변경 없이 다국어 메모리 사용 가능 |
| HOL Guard | [PR #3441](https://github.com/hashgraph-online/hol-guard/pull/3441) | Approved; still open | 처음엔 비활성인 MCP 기여를 제안. 노트 변경에 대한 권한 고지와 리뷰 기본값 포함. Guard 정책 아래 로컬 메모리를 옵트인할 수 있음 | 게시된 birkin-mnemosyne MCP 서버와 실제 도구 권한을 등록. 한국어 전용 Guard 수정이 아님 |
| OpenClaw | [PR #163588](https://github.com/openclaw/openclaw/pull/163588) | Open | Python stdio 번들 안내를 제안. 의존성, Gateway 서비스의 PATH, 영속 데이터, 실제 에이전트 세션 검증을 다룸. 번들 감지가 실행 증거라는 취급을 거부 | birkin-mnemosyne의 Python MCP 번들을 OpenClaw에서 사용하며 파생. 일반 설정 안내이며 새로운 코어 메모리 백엔드나 한국어 전용 수정이 아님 |
| Awesome Agent Memory | [PR #122](https://github.com/TeleAI-UAGI/Awesome-Agent-Memory/pull/122) | Closed; [landed by hand](https://github.com/TeleAI-UAGI/Awesome-Agent-Memory/commit/e5755368c00e4d21289c197e773966b6e6ed28a7) | 메인테이너가 Emerging 프로젝트에 로컬 Markdown 메모리 옵션을 공저자 표기를 유지한 채 추가해, 검색과 범위 제한 큐레이션을 발견하기 쉽게 함 | 수락된 birkin-mnemosyne 목록이 한국어 바이그램을 명시적으로 설명함 |

## 크레딧

[Birkin](https://github.com/ashmoonori-afk/birkin) 개인 에이전트에서 추출했습니다.
CJK 바이그램 BM25 접근은 같은 작가가 쓴 oh-my-openagent의 메모리 회상
[PR #9209](https://github.com/code-yeongyu/oh-my-openagent/pull/9209)에서
채택되었습니다. 어휘 동률 해소와 완전한 어휘 매칭을 먼저 유지하는 것은 그 PR의
리뷰를 따릅니다.

히어로 이미지는 AI가 생성했습니다(ChatGPT 이미지 생성).

로컬 파일 메모리, 메모리 팰리스, BM25, 에빙하우스 망각, 계획 후 실행 안전에는
선행 사례가 있으며, 개별 재료는 새것이 아닙니다. birkin-mnemosyne은 표준
라이브러리 어휘 기반과, 코드로 범위가 제한된 공급자 이식형 계획 전용
큐레이션을 결합합니다. 같은 신화 이름을 공유하는 병행 그래프 메모리 프로젝트와는
관련이 없습니다. Python 패키지는 `birkin_mnemosyne`으로 임포트됩니다.

## 라이선스

MIT. [LICENSE](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/LICENSE)와 [NOTICE](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/NOTICE)를 참고하세요.
