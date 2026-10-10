![birkin-mnemosyne - 에이전트를 위한 작은 다국어 메모리: 세 개의 노트 카드가 빛나는 실로 검색 렌즈에 연결된 모습](https://raw.githubusercontent.com/ashmoonori-afk/birkin-mnemosyne/main/docs/assets/hero.png)

# birkin-mnemosyne

birkin-mnemosyne은 개인 에이전트를 위한 로컬 Markdown 메모리입니다. 다국어
BM25 검색, 사용 기반 감쇠(decay)와 영역(zone) 우선순위, 그리고 결정적 실행기가
파일 작업 범위를 제한하는 공급자 이식형 큐레이션을 제공합니다. 코어는 런타임
의존성이 전혀 없고, 노트를 저장하거나 검색하는 데 모델이나 API 키가 필요하지
않습니다. 노트는 읽기, grep, diff가 가능한 형식 그대로 유지되며, 선택 사항인
MCP 서버가 볼트를 에이전트 클라이언트에 연결하고, 옵트인 의미 모드(opt-in
semantic mode)가 의미 기반 검색을 더해 줍니다.

## 설치

Python >= 3.10이 필요합니다. PyPI에서 설치하세요:

```bash
pip install birkin-mnemosyne
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
패러프레이즈 MRR을 0.205에서 0.981과 0.952로 올렸습니다. 질문과 확장 모두
모델이 작성했으므로 상한선으로 읽어 주세요:
[검색 시점 쿼리 확장](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#search-time-query-expansion-core-zero-dependencies-opt-in-per-search).

## 항상 로드되는 메모리 INDEX(선택)

언제 읽어야 하는지(읽을 시점)에서 어떤 문서인지로 이어지는 **완전한 지도**를 시작
컨텍스트에 항상 담아 두고, 세부 내용은 필요할 때만 여는 기능입니다. INDEX는
v0.6.0부터 사용할 수 있습니다. 아래 설명하는 태스크 결합 읽기와 2단계 주제 맵은
main에 반영되어 있습니다. 아직 이들을 덮는 태그가 없어서 이 문서에서는 버전
표기를 붙이지 않습니다.

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

main에서는 태스크 결합 읽기를 쓸 수 있습니다. 호스트가 행동하기 전에
`StartupReader("my_vault").read([], task="Check Ingress DNS")`를 호출하면,
어휘 매칭된 문서를 선택적 조회의 top-k 상한이나 검색 폴백 없이 전체 내용으로
돌려줍니다. 같은 `task`를 MCP의 `memory_startup_read` / `memory_startup_verify`에
넘기세요. 인덱스된 Hermes `prefetch`는 이 경로를 자동으로 사용합니다. 어휘
한계와 완전 읽기 실패 동작은 아래 사용 가이드를 참고하세요.

main은 또한 단일 구조(flat) INDEX와 더 작은 2단계 주제 맵 중 하나를 선택합니다.
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

v0.6.0 가상 대형 노트 벤치마크는 전체 시작 페이로드를 **45,128에서
1,781 o200k_base 토큰**으로 줄였습니다. 분리된 고정 Sol·Claude 질문 세트는
모두 **12/12**를 유지했으며, 정확도 향상은 아닙니다. 작은 노트의 태스크
비용은 늘어날 수 있습니다. [사용·복구 가이드](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/memory-index-guide.md)와
[측정값·분모·회귀](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/memory-index-results.md)를 참고하세요.

## 수치가 말해 주는 것

아래 모든 검색 품질은 [RESULTS.md](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#optional-semantic-mode-semantic-extra)에서
그대로 가져온 **최종 고정 테스트 분할**입니다. 합성 말뭉치는 6개 언어의 골드
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
| ko | 0.579 -> 0.640 | 0.654 -> 0.728 |
| ja | 0.794 -> 0.843 | 0.848 -> 0.899 |
| zh | 0.818 -> 0.871 | 0.867 -> 0.926 |
| es | 0.698 -> 0.744 | 0.769 -> 0.861 |
| de | 0.689 -> 0.749 | 0.756 -> 0.822 |

#### 1,000개 노트

| 언어 | MRR: 코어 -> 의미 | R@5: 코어 -> 의미 |
|---|---|---|
| en | 0.581 -> 0.620 | 0.679 -> 0.714 |
| ko | 0.554 -> 0.614 | 0.613 -> 0.683 |
| ja | 0.782 -> 0.809 | 0.848 -> 0.909 |
| zh | 0.766 -> 0.823 | 0.830 -> 0.881 |
| es | 0.655 -> 0.686 | 0.694 -> 0.713 |
| de | 0.664 -> 0.708 | 0.741 -> 0.770 |

#### 10,000개 노트

| 언어 | MRR: 코어 -> 의미 | R@5: 코어 -> 의미 |
|---|---|---|
| en | 0.568 -> 0.604 | 0.655 -> 0.675 |
| ko | 0.559 -> 0.608 | 0.609 -> 0.658 |
| ja | 0.782 -> 0.816 | 0.848 -> 0.879 |
| zh | 0.764 -> 0.782 | **0.822 -> 0.815** |
| es | 0.673 -> 0.681 | 0.704 -> 0.704 |
| de | 0.681 -> 0.708 | 0.741 -> 0.748 |

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
| 1000 | de | 0.671 | 0.692 |
| 10000 | en | 0.588 | 0.639 |
| 10000 | ko | 0.570 | 0.608 |
| 10000 | ja | 0.763 | 0.828 |
| 10000 | zh | 0.746 | 0.764 |
| 10000 | es | 0.653 | **0.639** |
| 10000 | de | 0.671 | 0.687 |

#### gpt-6.1-sol

| 노트 수 | 언어 | 코어 MRR | 의미 MRR |
|---|---|---|---|
| 160 | en | 0.524 | 0.559 |
| 160 | ko | 0.612 | 0.671 |
| 160 | ja | 0.827 | 0.840 |
| 160 | zh | 0.811 | 0.877 |
| 160 | es | 0.628 | 0.711 |
| 160 | de | 0.612 | 0.663 |
| 1000 | en | 0.512 | 0.542 |
| 1000 | ko | 0.609 | 0.674 |
| 1000 | ja | 0.821 | 0.851 |
| 1000 | zh | 0.762 | 0.847 |
| 1000 | es | 0.577 | 0.652 |
| 1000 | de | 0.595 | 0.629 |
| 10000 | en | 0.496 | 0.517 |
| 10000 | ko | 0.613 | 0.668 |
| 10000 | ja | 0.826 | 0.828 |
| 10000 | zh | 0.777 | **0.776** |
| 10000 | es | 0.609 | 0.643 |
| 10000 | de | 0.622 | 0.648 |

#### claude-fable-5.1

| 노트 수 | 언어 | 코어 MRR | 의미 MRR |
|---|---|---|---|
| 160 | en | 0.643 | 0.691 |
| 160 | ko | 0.530 | 0.581 |
| 160 | ja | 0.781 | 0.876 |
| 160 | zh | 0.822 | 0.884 |
| 160 | es | 0.775 | 0.814 |
| 160 | de | 0.761 | 0.844 |
| 1000 | en | 0.641 | 0.673 |
| 1000 | ko | 0.487 | 0.548 |
| 1000 | ja | 0.742 | 0.781 |
| 1000 | zh | 0.785 | 0.829 |
| 1000 | es | 0.736 | 0.761 |
| 1000 | de | 0.726 | 0.804 |
| 10000 | en | 0.621 | 0.655 |
| 10000 | ko | 0.493 | 0.548 |
| 10000 | ja | 0.759 | 0.790 |
| 10000 | zh | 0.770 | 0.807 |
| 10000 | es | 0.756 | 0.763 |
| 10000 | de | 0.749 | 0.787 |

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

### 설치 용량과 메모리

Apple M1, macOS arm64 측정값이며 서비스 수준 보장이 아닙니다. 모든 화살표는
**코어에서 의미 모드로**입니다. 설치 크기는 엑스트라 의존성을 포함하되 준비된
모델은 제외해 **0.18 MB에서 38.2 MB**입니다. 첫 준비에는 약 530 MB 다운로드가
필요하고, 압축 모델은 디스크에서 약 140 MB입니다. 준비는 다운로드를 지우지
않습니다. 원본 모델은 Hugging Face 캐시에 남으므로 총 약 670 MB를 예산으로
잡으세요. 캐시는 `$HF_HUB_CACHE`이며, 기본값은 `$HF_HOME/hub`, 그다음
`~/.cache/huggingface/hub`입니다. 모델은 그 안의
`models--minishlab--potion-multilingual-128M` 폴더입니다. 모델을 준비한 뒤에는
그 폴더를 지워 약 530 MB를 돌려받을 수 있고(huggingface_hub 1.x 이상에서는
`hf cache rm model/minishlab/potion-multilingual-128M`이 같은 일을 합니다),
압축 모델은 계속 동작하며 다시 준비할 때만 새로 다운로드합니다. 기본 모델은
고정된 커밋에서 가져오며, 그 커밋은 준비된 모델과 벡터 사이드카에 함께
기록됩니다. 메모리 예산은 코어 위에 150 MB였고, 측정된 가장 큰 증가는
인덱싱 중 61 MB였습니다. 준비된 모델 시작 예산은 1초였으며, 레퍼런스 타이밍
실행에서 가장 느린 의미 모드 시작은 439 ms였습니다.

#### 인덱스와 메모리

| 노트 수 | 디스크의 인덱스 | RSS: 검색 | RSS: 인덱싱 |
|---|---|---|---|
| 160 | 0.07 MB -> 0.09 MB | 25 -> 48 MB | 26 -> 83 MB |
| 1000 | 0.35 MB -> 0.43 MB | 34 -> 56 MB | 40 -> 101 MB |
| 10000 | 3.27 MB -> 4.08 MB | 138 -> 159 MB | 170 -> 231 MB |

#### 시작 시간과 지연 시간

| 노트 수 | 시작 중앙값(최대) | p50 | p95 |
|---|---|---|---|
| 160 | 41 ms (42) -> 89 ms (95) | 0.5 -> 1.6 ms | 0.6 -> 3.4 ms |
| 1000 | 65 ms (98) -> 125 ms (132) | 3.1 -> 7.4 ms | 3.9 -> 8.4 ms |
| 10000 | 307 ms (547) -> 382 ms (439) | 35.4 -> 75.6 ms | 37.8 -> 79.4 ms |

RSS는 검색과 볼트 전체 인덱싱 각각의 분리된 새 프로세스에서 잰 최대 상주
메모리입니다. 시작에는 인터프리터 시작, 임포트, 인덱스 로드, 첫 쿼리가
포함됩니다. 레퍼런스 타이밍은 더 낮은 머신 부하(1분 평균 부하 5.6~7.8)에서
시작 셀당 10개 프로세스와 웜 프로세스의 테스트 쿼리 300개로 측정했습니다.
지연 시간은 볼트 크기와 머신 부하에 따라 늘어납니다. `semantic_test_run.json`의
타이밍 필드는 **레퍼런스가 아닙니다**. RESULTS.md에서 따로 측정한 시작·지연
표를 사용하세요.

## 솔직한 한계

- **기본 코어에서 한국어는 개선되지 않습니다.** 이전 토크나이저 대비
  10,000개 노트에서 MRR은 **0.569에서 0.559**입니다. 영어 어간은 코드
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
  측정하지 않았습니다. 설치 용량 측정은 macOS arm64만 다룹니다.
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

커밋된 품질 실행은 [semantic_test_run.json](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/semantic_test_run.json)입니다.
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

### 도구

| 도구 | 하는 일 | 안전한 기본값 |
|---|---|---|
| `memory_search` | 스니펫이 있는 BM25 + 감쇠 + 영역 순위 결과. 선택 사항인 `synonyms` / `keywords` / `related` / `note_line`이 쿼리를 넓힘 | 읽기 전용 |
| `memory_get_note` | `version`이 있는 전체 노트. 사용으로 집계됨 | - |
| `memory_list` | 영역별 노트, 페이지네이션 | 읽기 전용 |
| `memory_remember` | 노트 쓰기: `mode="create"` / `"append"` / `"replace"` | `create`는 절대 덮어쓰지 않음. `replace`는 `expected_version` 필요 |
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
합니다. MCP에서 파일을 제거하는 유일한 곳은 `memory_review_undo`로, 원본
바이트를 복원·검증한 뒤에만 리뷰의 아카이브 사본을 삭제합니다.
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
`memory_review_undo`가 복원합니다. 예산 이내에서는 기존 클라이언트에 새 키가
보이지 않습니다.

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
    VaultMemory,        # write_note / rezone / digest 편의 래퍼
    ProfileMemory,      # 백그라운드 검토 역할 프로필 영속화
    ProfileReviewError, # 잘못된 리뷰어 출력
    run_curation_pass,  # 안전한 큐레이션 드라이버
    evaluate_plan,      # 구조화 계획 게이트(기본 드라이 런)
    get_completer,      # 공급자 레지스트리(claude|codex|api|gemini|local)
    validate_clamp,     # 적용 없이 계획을 검사하고 싶을 때의 게이트
    build_plan_prompt, extract_plan, mechanical_catalog,
    slug, tokenize, bm25_scores,
)
```

주요 `Mnemosyne` 메서드: `refresh()`,
`search(query, limit, zone, expansions=None)`, `related(slug)`,
`record_access(slug)`, `stale()`, `rezone(slug, zone)`, `zone_priorities()`,
`stats()`.

## 볼트 레이아웃과 설정

노트는 슬러그 이름의 Markdown 파일이며 YAML 프론트매터와 `[[wikilinks]]`를
씁니다. 영역은 한 단계 디렉터리이고, 볼트 루트가 인박스입니다.

```text
my_vault/
  inbox-note.md
  devops/
    ingress-dns.md
  people/
  projects/
  identity/
  knowledge/
  journal/
  system/                       # ProfileMemory가 소유하는 역할 파일
  _archive/                     # 소프트 삭제된 노트
  .mnemosyne-memory-index/       # 옵트인; index.json 라우팅과 상주 맥락 맵
  .mnemosyne-index.json.z        # 다시 만들 수 있는 압축 인덱스 캐시
  .mnemosyne-dynamics.json       # 영속 사용 상태
  .mnemosyne-vectors.npz         # 다시 만들 수 있는 의미 벡터 캐시
  .mnemosyne-reviews/            # 리뷰 실행 취소 저널(<transaction-id>.json)
  .mnemosyne-mcp.lock            # 프로세스 간 쓰기 잠금
```

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
MCP 경로와 증거 설정은 [MCP 서버 레퍼런스](#mcp-server-claude-code-claude-desktop-codex-cli-cursor)에 있습니다.

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