# 🚙 Coolingverse-data : 유휴 주차공간 공유 B2G 플랫폼 데이터 파이프라인

본 레포지토리는 지자체(성남시 분당구, 부천시 등)의 불법주정차 단속 데이터, 민간 아파트 유휴 주차면 데이터, 100m 공간 격자 데이터를 융합하여, **도심 주차난 해소를 위한 최적의 정책 타겟 구역을 도출하는 B2G 의사결정 지원 시스템(Decision Support System)**의 데이터 파이프라인입니다.

## 📌 핵심 기획 의도 (Core Value)
기존의 단순 '단속 건수' 기반의 정책 결정에서 벗어나, **'주차 수요(불법주정차)'와 '주차 공급(인근 아파트 유휴 주차면)'을 독립 변수로 분리**했습니다. 이를 통해 지자체가 한정된 예산을 바탕으로 투트랙(Two-Track) 주차 정책을 수립할 수 있는 강력한 인사이트를 제공합니다.
* 🚨 **Red Zone (수요 폭발 + 공급 제로):** 공영주차장 신설 등 물리적 인프라 예산의 우선 투입이 필요한 구역
* 🟢 **Green Zone (수요 폭발 + 공급 넉넉):** 예산 투입 없이 당사의 '유휴 주차장 매칭 플랫폼' 도입만으로 즉시 주차난 해소가 가능한 영업 타겟 구역

---

## 🛠️ 데이터 파이프라인 모듈 (Pipeline Modules)
전체 파이프라인은 유지보수와 협업 효율성을 위해 총 5개의 독립된 모듈로 분할되어 있습니다.

### 01. Geocoding_and_Cleansing.ipynb (하이브리드 지오코딩 엔진)
* 공공 주정차 단속 데이터의 불규칙한 주소 텍스트 정제 (정규표현식 기반 5-Step Fallback 파이프라인 적용)
* 카카오 로컬 API 기반 멀티스레딩 지오코딩으로 **99% 이상의 좌표 매칭률** 달성
* 주말 및 법정 공휴일 완벽 배제를 통한 '순수 평일 일과 시간' 트래픽 데이터 추출

### 02. Apartment_Preprocessing.ipynb (아파트 유휴 주차면 전처리)
* 아파트 단지 주소 기반 지오코딩 및 다중 Fallback을 통한 100% 좌표 매칭 완료
* 지상/지하 주차장 외부인 개방 여부(Y/N) 파싱 로직 구현
* 지자체별(부천시 등) 평일 낮 통근 이탈률을 적용한 실질 공유 가능 '유휴 주차면 수(`open_count`)' 산출

### 03. Air_Quality_Pipeline.ipynb (대기질 데이터 엔지니어링)
* 1년 치 지역별 대기질 측정소 엑셀 데이터 통합 및 전처리
* **결측치 3단계 방어 로직:** 선형 보간 ➔ 자가 과거 평균 ➔ 타 지역 가중치 평균을 통한 시뮬레이션 블랙홀 완벽 차단
* 도심 대기 데이터를 도로변 대기질 수준으로 현실화하는 3차원(지역별/월별/시간대별) 가중치 보정 연산

### 04. Grid_Preprocessing.ipynb (공간 격자(Grid) 생성 및 필터링)
* GIS 수치지도형 100m x 100m 격자 파일(`.shp`)을 WGS84 좌표계로 변환 및 Bounding Box 추출
* 대상 지역(분당구, 부천시 등)의 실제 위경도 경계에 맞춰 활성 격자 데이터셋 정제 및 정수형 `grid_id` 재부여

### 05. Risk_Index_Modeling.ipynb (B2G 의사결정용 위험 지수 산출)
* `scipy.spatial.cKDTree`를 도입하여 단속, 아파트, 대기질 데이터를 활성 격자에 **1초 이내 초고속 매핑**
* 수요 압박(Log 변환 적용)과 공급 부족(유휴면 역수 적용)을 독립 결합하여 현실적인 타겟 지수 산출
* 반복문(`iterrows`)을 배제한 완벽한 **벡터화(Vectorization) 연산**으로 24시간 매트릭스 지수 산출 속도 99% 단축

---

## 🚀 사용 기술 스택 (Tech Stack)
* **Language:** Python 3
* **Data Processing & Math:** `pandas`, `numpy`, `scipy` (cKDTree)
* **Geospatial Analysis:** `geopandas`, `shapely`
* **Visualization:** `folium`, `matplotlib`, `seaborn`, Kakao Maps API (Heatmap.js)
* **Environment & API:** Google Colab, GitHub, Kakao Local API

---

## 📁 프로젝트 구조 (Project Structure)
```text
├── README.md
├── 01_Geocoding_and_Cleansing.ipynb
├── 02_Apartment_Preprocessing.ipynb
├── 03_Air_Quality_Pipeline.ipynb
├── 04_Grid_Preprocessing.ipynb
└── 05_Risk_Index_Modeling.ipynb
```

## 운영 CLI와 지역 격리

노트북은 분석 근거로 보존하고 `src/coolingverse_pipeline`을 운영 적재에 사용합니다. 각 실행은 한 지역만
입력받으며 정규화, 대기질 fallback, KD-Tree, 24시간 확장을 모두
`region_code × analysis_year × analysis_month` 경계 안에서 수행합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check src tests
pytest
```

비공개 Object Storage 버킷 `coolingverse-data`의 원천 버전에는 `manifest.json`을 두며, `grids`,
`enforcement`, `apartments`, `air_quality` CSV의 버킷 상대 경로와 SHA-256을 기록합니다. 실패한 단속
지오코딩 행은 삭제하지 않고 `region_code`를 유지한 채 `grid_code`만 비웁니다.

운영 실행은 GitHub Actions의 `Production data pipeline`을 수동 실행합니다. 품질 검사와 ADB staging
적재가 성공한 뒤 활성 포인터만 전환하고, 백엔드 readiness 실패 시 이전 포인터로 복구합니다.
