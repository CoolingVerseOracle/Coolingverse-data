# 🚙 Coolingverse-data : 유휴 주차공간 공유 B2G 플랫폼 데이터 파이프라인

본 레포지토리는 지자체(성남시 분당구, 부천시 등)의 불법주정차 단속 데이터와 민간 아파트 유휴 주차면 데이터를 융합하여, **도심 주차난 해소를 위한 최적의 정책 타겟 구역을 도출하는 100m 격자(Grid) 기반 B2G 의사결정 지원 시스템(Decision Support System)**의 데이터 파이프라인입니다.

## 📌 핵심 기획 의도 (Core Value)
기존의 단순 '단속 건수' 기반의 정책 결정에서 벗어나, **'주차 수요(불법주정차)'와 '주차 공급(인근 아파트 유휴 주차면)'을 독립 변수로 분리**했습니다. 이를 통해 지자체가 한정된 예산을 바탕으로 투트랙(Two-Track) 주차 정책을 수립할 수 있는 강력한 인사이트를 제공합니다.
* 🚨 **Red Zone (수요 폭발 + 공급 제로):** 공영주차장 신설 등 물리적 인프라 예산의 우선 투입이 필요한 구역
* 🟢 **Green Zone (수요 폭발 + 공급 넉넉):** 예산 투입 없이 당사의 '유휴 주차장 매칭 플랫폼' 도입만으로 즉시 주차난 해소가 가능한 영업 타겟 구역

## 🛠 데이터 파이프라인 핵심 기술 및 모듈 (Key Features & Modules)
전체 파이프라인은 유지보수와 팀 협업을 위해 4개의 독립된 모듈로 분할되어 있습니다.

### 01. Geocoding_and_Cleansing.ipynb (하이브리드 지오코딩 엔진)
* 공공데이터의 불규칙한 주소 텍스트를 위경도(Lat/Lng)로 변환하는 정밀 파이프라인 구축
* 정규표현식(Regex)과 카카오 로컬 API를 결합한 **5-Step Fallback (순차 구제) 로직** 적용으로 **99% 이상의 좌표 매칭률** 달성
* 주말 및 법정 공휴일 완벽 배제를 통한 '순수 평일 일과 시간' 트래픽 데이터 추출

### 02. Air_Quality_Preprocessing.ipynb (대기질 데이터 엔지니어링)
* 1년 치 지역별 대기질 측정소 엑셀 데이터 통합 및 전처리
* **결측치 3단계 방어 로직:** 선형 보간(Linear Interpolation) ➔ 자가 과거 평균 ➔ 타 지역 가중치 평균을 통한 시뮬레이션 블랙홀 완벽 차단
* 도심 대기 데이터를 도로변 대기질 수준으로 현실화하는 3차원(지역별/월별/시간대별) 가중치 보정 연산

### 03. Spatial_Mapping_and_ERD.ipynb (고속 공간 탐색 및 격자 매핑)
* `GeoPandas`를 활용하여 대상 지역을 **100m x 100m 단위의 공간 격자(Grid)**로 분할
* `scipy.spatial.cKDTree` 알고리즘을 도입하여 20만 건 이상의 단속 데이터, 아파트 좌표, 대기질 데이터를 최단 거리 격자에 **1초 이내 초고속 할당(Mapping)**
* 프론트엔드/백엔드 DB 적재에 최적화된 테이블 스키마 일괄 정규화

### 04. Risk_Index_Modeling.ipynb (B2G 의사결정용 위험 지수 산출)
* 수요 압박(비대칭 분포 보정을 위한 Log 변환)과 공급 부족(유휴면 역수 적용)을 결합하여 현실적인 타겟 지수 산출
* 반복문(`iterrows`)을 배제한 완벽한 **벡터화(Vectorization) 연산**으로 24시간 매트릭스 지수 산출 속도 99% 단축
* 환경 민감도(대기질 법정 기준치 대비 비율) 및 시간대별 교통 혼잡도 가중치 결합

## 🚀 사용 기술 스택 (Tech Stack)
* **Language:** Python 3
* **Data Processing & Math:** `pandas`, `numpy`, `scipy` (cKDTree)
* **Geospatial Analysis:** `geopandas`, `shapely`
* **Visualization:** `folium`, `matplotlib`, `seaborn`, Kakao Maps API (Heatmap.js)
* **Environment & API:** Google Colab, GitHub, Kakao Local API

## 📁 프로젝트 구조 (Project Structure)
```text
├── README.md
├── 01_Geocoding_and_Cleansing.ipynb
├── 02_Air_Quality_Preprocessing.ipynb
├── 03_Spatial_Mapping_and_ERD.ipynb
└── 04_Risk_Index_Modeling.ipynb
