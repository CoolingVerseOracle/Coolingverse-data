# Coolingverse-data
유휴주차공간 활용 데이터 전처리 파이프라인 설계
## 🛠️ 데이터 파이프라인 모듈 (Pipeline Modules)

전체 파이프라인은 유지보수와 팀 협업을 위해 4개의 독립된 모듈로 분할되어 있습니다.

**01. Geocoding_and_Cleansing.ipynb**
* 공공 주정차 단속 데이터의 텍스트 노이즈 정제 (5단계 정규식 파이프라인 적용)
* 카카오 로컬 API 기반 멀티스레딩 지오코딩 (일일 한도 우회 및 속도 최적화)
* 주말 및 법정 공휴일 배제를 통한 '순수 출퇴근 평일' 데이터 추출

**02. Air_Quality_Preprocessing.ipynb**
* 1년 치 지역별 대기질 엑셀 데이터 통합 및 결측치 보정
* 도심 대기 및 도로변 대기질 데이터를 활용한 환경 민감도(Env Sensitivity) 가중치 산출

**03. Risk_Index_Modeling.ipynb**
* `Geopandas`를 활용한 100M 단위 도심 활성 격자(Active Grid) 공간 매핑
* `scipy.spatial.cKDTree`를 도입하여 12만 개 격자와 최단 거리 대기질 측정소 초고속 매핑 
* 반복문(`iterrows`)을 배제한 완벽한 벡터화(Vectorization) 연산으로 24시간 위험 지수 산출 속도 99% 단축

## ⚙️ 기술 스택 (Tech Stack)
* **Language:** Python
* **Data Processing:** Pandas, NumPy
* **Geospatial Analysis:** GeoPandas, SciPy (cKDTree), Shapely
* **Visualization:** Folium, Kakao Maps API (Heatmap.js)
* **Environment:** Google Colab, GitHub
