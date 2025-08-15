package com.reely.controller;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.reely.common.util.CommonUtil;
import com.reely.dto.KmdbDto;
import com.reely.dto.KobisDto;
import com.reely.dto.MovieDto;
import com.reely.dto.TmdbDto;
import com.reely.dto.TmdbDto.ProductionCompany;
import com.reely.dto.SpotifyDto;
import com.reely.dto.SpotifyDto.SpotifyAlbumTracksDto;
import com.reely.dto.SpotifyDto.Tracks;
import com.reely.mapper.MovieMapper;
import com.reely.service.KmdbMovieFeignClient;
import com.reely.service.KobisMovieFeignClient;
import com.reely.service.MovieService;
import com.reely.service.SpotifyFeignClient;
import com.reely.service.TmdbMovieFeignClient;

@RestController
@RequestMapping("/api")
public class MovieController {

    private final KobisMovieFeignClient kobisFeignClient;
    private final KmdbMovieFeignClient kmdbFeignClient;
    private final TmdbMovieFeignClient tmdbMovieClient;
    private final SpotifyFeignClient spotifyClient;
    // tmdb 이미지 url
    private static final String imageBaseUrl = "https://image.tmdb.org/t/p/original";
    private final MovieService movieService;
    private final MovieMapper movieMapper;

    String kobisKey = "9eaf43c6cd0bde9c0862c1c2c1e4b434"; 
    String kmdbKey = "MZ53N9719N5IH6Z7G2R9";
    String tmdbKey = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI5MWJlODU2OGFhYzg4OGMyMzYxOTliMjBmNTBiZWFhNiIsIm5iZiI6MTc0NDYxNzA1Ni43NjQsInN1YiI6IjY3ZmNiZTYwZWMyMmJhM2I0OWQ5ODg0YyIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.SH_t-hN5ptu6cBiLvpK0DSU0U56ZKWwaXUIchYFkMQM";
    String spotifyClientId = "5b2c9e587cf74849aa331f4c8cf79a9f";
    String spotifyClientSecret = "4ccb21a2472048c69fe4741655125741";

    public MovieController(MovieMapper movieMapper, MovieService movieService, KobisMovieFeignClient kobisFeignClient, KmdbMovieFeignClient kmdbFeignClient, TmdbMovieFeignClient tmdbFeignClient, SpotifyFeignClient spotifyClient) {
        this.movieService = movieService;
        this.movieMapper = movieMapper;
        this.kobisFeignClient = kobisFeignClient;
        this.kmdbFeignClient = kmdbFeignClient;
        this.tmdbMovieClient = tmdbFeignClient;
        this.spotifyClient = spotifyClient;
    }

    String localFilePath = System.getProperty("user.dir"); // 현재 작업 디렉토리
    String filePath = "/volumes"; // 프로젝트 내부 경로
    
    @GetMapping(value = "/getDailyBoxOfficeList", produces = "application/json")
    public String getDailyBoxOfficeList(KobisDto kobisDto) {
        LocalDate today = LocalDate.now();
        // 오늘 날짜로부터 1일전
        LocalDate oneDayAgo = today.minusDays(1);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyyMMdd");
        String targetDt = oneDayAgo.format(formatter);
        String jsonData = kobisFeignClient.getDailyBoxOfficeList(kobisKey, targetDt,"K");
        System.out.println(jsonData);

        return "Hello World";
    }

    @GetMapping(value = "/getMoviesInfo/{movieNm}" , produces = "application/json")
    public List<MovieDto> getMoviesInfo(@PathVariable("movieNm") String movieNm) {
        System.out.println("===========================Starting movie search==========================="+movieNm);
        ObjectMapper objectMapper = new ObjectMapper();
        JSONParser parser = new JSONParser();
        List<MovieDto> movieDtoList = new ArrayList<>();
        List<MovieDto> searchMovieList = new ArrayList<>();
        
        try {
            // 1. 모든 API에서 데이터 수집
            List<KmdbDto> kmdbList = fetchKmdbData(movieNm, objectMapper);
            List<KobisDto> kobisList = fetchKobisData(movieNm, objectMapper);
            List<TmdbMovieSearchResult> tmdbList = fetchTmdbData(movieNm, objectMapper);
            
            System.out.println("Data collected - KMDB: " + kmdbList.size() + ", KOBIS: " + kobisList.size() + ", TMDB: " + tmdbList.size());
            
            // 2. KMDB 기준으로 영화 매칭 및 병합 (우선순위 변경)
            for (KmdbDto kmdbDto : kmdbList) {
                try {
                    MovieDto movieDto = matchAndMergeMovieData(kmdbDto, kobisList, tmdbList, objectMapper, parser);
                    if (movieDto != null) {
                        movieDtoList.add(movieDto);
                        System.out.println("Successfully processed movie: " + movieDto.getMovieKoNm());
                    }
                } catch (Exception e) {
                    System.err.println("Error processing movie: " + kmdbDto.getTitle() + " - " + e.getMessage());
                    e.printStackTrace();
                }
            }

            searchMovieList = searchMovieByName(movieNm);
            
        } catch (Exception e) {
            e.printStackTrace();
        }
        
        return searchMovieList;
    }
    
    @GetMapping(value = "/getMoviesInfo2/{movieNm}" , produces = "application/json")
    public List<MovieDto> getMoviesInfo2(@PathVariable("movieNm") String movieNm) {
        System.out.println("===========================Starting movie search2 ==========================="+movieNm);
        List<MovieDto> searchMovieList = new ArrayList<>();
        
        try {
            

            searchMovieList = searchMovieByName(movieNm);
            
        } catch (Exception e) {
            e.printStackTrace();
        }
        
        return searchMovieList;
    }

    /**
     * KOBIS API에서 영화 데이터 수집
     */
    private List<KobisDto> fetchKobisData(String movieNm, ObjectMapper objectMapper) {
        List<KobisDto> kobisList = new ArrayList<>();
        
        try {
            String jsonData = kobisFeignClient.getMovieInfo(kobisKey, movieNm);
            System.out.println("===========================KOBIS Response===========================");
            System.out.println(jsonData);
            
            JSONParser parser = new JSONParser();
            JSONObject jsonObject = (JSONObject) parser.parse(jsonData);
            JSONObject movieListResult = (JSONObject) jsonObject.get("movieListResult");
            JSONArray movieList = (JSONArray) movieListResult.get("movieList");
            
            for (int i = 0; i < movieList.size(); i++) {
                JSONObject movie = (JSONObject) movieList.get(i);
                KobisDto kobisDto = objectMapper.readValue(movie.toJSONString(), KobisDto.class);
                kobisList.add(kobisDto);
            }
            
        } catch (Exception e) {
            System.err.println("Error fetching KOBIS data: " + e.getMessage());
            e.printStackTrace();
        }
        
        return kobisList;
    }
    
    /**
     * KMDB API에서 영화 데이터 수집
     */
    private List<KmdbDto> fetchKmdbData(String movieNm, ObjectMapper objectMapper) {
        List<KmdbDto> kmdbList = new ArrayList<>();
        
        try {
            String kmJsonData = kmdbFeignClient.getMovieInfo(kmdbKey, movieNm);
            System.out.println("===========================KMDB Response===========================");
            System.out.println(kmJsonData);
            
            if (kmJsonData != null && !kmJsonData.isEmpty()) {
                JsonNode root = objectMapper.readTree(kmJsonData);
                
                if (root.has("Data") && root.get("Data").isArray()) {
                    JsonNode dataArray = root.get("Data");
                    
                    if (dataArray.size() > 0) {
                        JsonNode firstData = dataArray.get(0);
                        
                        if (firstData.has("Result") && firstData.get("Result").isArray()) {
                            JsonNode resultArray = firstData.get("Result");
                            
                            for (JsonNode resultNode : resultArray) {
                                try {
                                    KmdbDto dto = objectMapper.treeToValue(resultNode, KmdbDto.class);
                                    if (dto != null) {
                                        // 제목 정리
                                        cleanKmdbTitle(dto);
                                        kmdbList.add(dto);
                                    }
                                } catch (Exception parseEx) {
                                    System.err.println("Error parsing individual KMDB result: " + parseEx.getMessage());
                                }
                            }
                        }
                    }
                }
            }
            
        } catch (Exception e) {
            System.err.println("Error fetching KMDB data: " + e.getMessage());
            e.printStackTrace();
        }
        
        return kmdbList;
    }
    
    /**
     * TMDB API에서 영화 데이터 수집 (영어 제목으로 검색)
     */
    private List<TmdbMovieSearchResult> fetchTmdbData(String movieNm, ObjectMapper objectMapper) {
        List<TmdbMovieSearchResult> tmdbList = new ArrayList<>();
        
        try {
            // 영어 제목으로 검색 시도
            String tmJsonData = tmdbMovieClient.searchMovie("Bearer " + tmdbKey, movieNm, "en-US", 1);
            System.out.println("===========================TMDB Response===========================");
            System.out.println(tmJsonData);
            
            JsonNode jsonNode = objectMapper.readTree(tmJsonData);
            JsonNode results = jsonNode.get("results");
            
            if (results != null && results.isArray()) {
                for (JsonNode movie : results) {
                    TmdbMovieSearchResult tmdbResult = new TmdbMovieSearchResult();
                    tmdbResult.setId(movie.get("id").asText());
                    tmdbResult.setTitle(movie.get("title").asText());
                    tmdbResult.setOriginalTitle(movie.has("original_title") ? movie.get("original_title").asText() : "");
                    tmdbResult.setReleaseDate(movie.has("release_date") ? movie.get("release_date").asText() : "");
                    tmdbResult.setOriginalLanguage(movie.has("original_language") ? movie.get("original_language").asText() : "");
                    tmdbList.add(tmdbResult);
                }
            }
            
        } catch (Exception e) {
            System.err.println("Error fetching TMDB data: " + e.getMessage());
            e.printStackTrace();
        }
        
        return tmdbList;
    }
    
    /**
     * KMDB 영화를 기준으로 KOBIS, TMDB 데이터를 매칭하여 하나의 MovieDto로 병합 (기준 변경)
     */
    private MovieDto matchAndMergeMovieData(KmdbDto kmdbDto, List<KobisDto> kobisList, 
                                        List<TmdbMovieSearchResult> tmdbList, 
                                        ObjectMapper objectMapper, JSONParser parser) {
        try {
            System.out.println("Processing movie: " + kmdbDto.getTitle() + " (" + kmdbDto.getRepRlsDate() + ")");
            
            // KOBIS 매칭 (KMDB 기준)
            KobisDto matchedKobis = findMatchingKobisMovie(kmdbDto, kobisList);
            System.out.println("KOBIS match: " + (matchedKobis != null ? matchedKobis.getMovieNm() : "None"));
            
            // TMDB 매칭 (영어제목이 있는 경우)
            TmdbMovieSearchResult matchedTmdb = null;
            String englishTitle = getEnglishTitle(matchedKobis, kmdbDto);
            if (englishTitle != null && !englishTitle.isEmpty()) {
                matchedTmdb = findMatchingTmdbMovie(kmdbDto, matchedKobis, englishTitle, tmdbList);
                System.out.println("TMDB match: " + (matchedTmdb != null ? matchedTmdb.getTitle() : "None"));
            }
            
            // MovieDto 생성 및 데이터 병합 (KMDB 우선)
            MovieDto movieDto = createMovieDto(kmdbDto, matchedKobis, matchedTmdb);
            
            if (movieDto == null) {
                return null;
            }
            
            // 추가 데이터 처리
            processAdditionalData(movieDto, kmdbDto, matchedTmdb, objectMapper, parser);
            
            return movieDto;
            
        } catch (Exception e) {
            System.err.println("Error matching and merging movie data: " + e.getMessage());
            e.printStackTrace();
            return null;
        }
    }
    
    /**
     * KMDB 영화와 매칭되는 KOBIS 영화 찾기 (매칭 방향 변경)
     */
    private KobisDto findMatchingKobisMovie(KmdbDto kmdbDto, List<KobisDto> kobisList) {
        String kmdbTitle = kmdbDto.getTitle();
        String kmdbOpenDt = kmdbDto.getRepRlsDate();
        
        // 1. 제목 + 개봉일자 정확 매칭
        KobisDto exactMatch = kobisList.stream()
                .filter(kobis -> kmdbTitle.equals(kobis.getMovieNm()))
                .filter(kobis -> kmdbOpenDt != null && !kmdbOpenDt.isEmpty() && kmdbOpenDt.equals(kobis.getOpenDt()))
                .findFirst()
                .orElse(null);
        
        if (exactMatch != null) {
            return exactMatch;
        }
        
        // 2. 제목만 매칭 (개봉일자가 없거나 다른 경우)
        KobisDto titleMatch = kobisList.stream()
                .filter(kobis -> kmdbTitle.equals(kobis.getMovieNm()))
                .findFirst()
                .orElse(null);
        
        if (titleMatch != null) {
            return titleMatch;
        }
        
        // 3. 유사 제목 매칭
        return kobisList.stream()
                .filter(kobis -> isTitleSimilar(kmdbTitle, kobis.getMovieNm()))
                .findFirst()
                .orElse(null);
    }
    
    /**
     * KMDB/KOBIS 영화와 매칭되는 TMDB 영화 찾기 (기준 변경)
     */
    private TmdbMovieSearchResult findMatchingTmdbMovie(KmdbDto kmdbDto, KobisDto kobisDto, 
                                                    String englishTitle, List<TmdbMovieSearchResult> tmdbList) {
        String kmdbOpenDt = kmdbDto.getRepRlsDate();
        
        // 1. 영어 제목 + 개봉일자 매칭
        TmdbMovieSearchResult exactMatch = tmdbList.stream()
                .filter(tmdb -> isTitleSimilar(englishTitle, tmdb.getTitle()) || 
                            isTitleSimilar(englishTitle, tmdb.getOriginalTitle()))
                .filter(tmdb -> kmdbOpenDt != null && !kmdbOpenDt.isEmpty() && 
                            isDateMatching(kmdbOpenDt, tmdb.getReleaseDate()))
                .findFirst()
                .orElse(null);
        
        if (exactMatch != null) {
            return exactMatch;
        }
        
        // 2. 영어 제목만 매칭
        return tmdbList.stream()
                .filter(tmdb -> isTitleSimilar(englishTitle, tmdb.getTitle()) || 
                            isTitleSimilar(englishTitle, tmdb.getOriginalTitle()))
                .findFirst()
                .orElse(null);
    }
    
    /**
     * 영어 제목 추출 (KOBIS 또는 KMDB에서) - 순서 변경
     */
    private String getEnglishTitle(KobisDto kobisDto, KmdbDto kmdbDto) {
        // KMDB 우선
        if (kmdbDto != null && kmdbDto.getTitleEng() != null && !kmdbDto.getTitleEng().isEmpty()) {
            return kmdbDto.getTitleEng();
        }
        
        if (kobisDto != null && kobisDto.getMovieNmEn() != null && !kobisDto.getMovieNmEn().isEmpty()) {
            return kobisDto.getMovieNmEn();
        }
        
        return null;
    }
    
    /**
     * 매칭된 데이터들을 이용하여 MovieDto 생성 (KMDB 우선순위로 변경)
     */
    private MovieDto createMovieDto(KmdbDto kmdbDto, KobisDto kobisDto, TmdbMovieSearchResult tmdbDto) {
        try {
            // 등급 정보 추출 (KMDB 우선)
            String grade = "";
            if (kmdbDto != null && kmdbDto.getRatings() != null && 
                kmdbDto.getRatings().getRating() != null && !kmdbDto.getRatings().getRating().isEmpty()) {
                String raw = kmdbDto.getRatings().getRating().get(0).getRatingGrade();
                grade = raw != null ? raw.split("\\|\\|")[0] : "";
            }
            
            // 줄거리 추출 (KMDB 우선)
            String plotText = "";
            if (kmdbDto != null && kmdbDto.getPlots() != null) {
                KmdbDto.PlotsWrapper plotsWrapper = kmdbDto.getPlots();
                if (plotsWrapper != null && plotsWrapper.getPlot() != null && !plotsWrapper.getPlot().isEmpty()) {
                    plotText = plotsWrapper.getPlot().get(0).getPlotText();
                }
            }
    
            // 수상 정보 추출 (KMDB 우선)
            List<String> awards = new ArrayList<>();
            if (kmdbDto != null) {
                if (kmdbDto.getAwards1() != null && !kmdbDto.getAwards1().isEmpty()) {
                    awards.add(kmdbDto.getAwards1());
                }
                if (kmdbDto.getAwards2() != null && !kmdbDto.getAwards2().isEmpty()) {
                    awards.add(kmdbDto.getAwards2());
                }
            }
    
            int newMovieId = movieMapper.getMovieId();
            
            // 안전한 값 추출 (KMDB 우선순위로 변경)
            String movieKoNm = (kmdbDto != null && kmdbDto.getTitle() != null && !kmdbDto.getTitle().isEmpty()) ? 
                              kmdbDto.getTitle() : 
                              (kobisDto != null && kobisDto.getMovieNm() != null ? kobisDto.getMovieNm() : "");
                              
            String movieEnNm = getEnglishTitle(kobisDto, kmdbDto);
            
            String moviePrDt = (kmdbDto != null && kmdbDto.getProdYear() != null && !kmdbDto.getProdYear().isEmpty()) ? 
                              kmdbDto.getProdYear() :
                              (kobisDto != null && kobisDto.getPrdtYear() != null ? kobisDto.getPrdtYear() : "");
                              
            // 개봉일 처리 - null 체크 강화
            String movieOpenDt = null;
            if (kmdbDto != null && kmdbDto.getRepRlsDate() != null && !kmdbDto.getRepRlsDate().trim().isEmpty()) {
                movieOpenDt = kmdbDto.getRepRlsDate();
            } else if (kobisDto != null && kobisDto.getOpenDt() != null && !kobisDto.getOpenDt().trim().isEmpty()) {
                movieOpenDt = kobisDto.getOpenDt();
            }
            // movieOpenDt가 null이면 그대로 null로 유지
            
            Integer movieRuntime = null;
            if (kmdbDto != null && kmdbDto.getRuntime() != null && !kmdbDto.getRuntime().isEmpty()) {
                try {
                    movieRuntime = Integer.parseInt(kmdbDto.getRuntime());
                } catch (NumberFormatException e) {
                    System.err.println("Invalid runtime format: " + kmdbDto.getRuntime());
                }
            }
            
            // 장르 정보 - KMDB 우선
            String genre = "";
            if (kmdbDto != null && kmdbDto.getGenre() != null && !kmdbDto.getGenre().isEmpty()) {
                genre = kmdbDto.getGenre();
            } else if (kobisDto != null && kobisDto.getGenreAlt() != null && !kobisDto.getGenreAlt().isEmpty()) {
                genre = kobisDto.getGenreAlt();
            }
            System.out.println("===========================tmdbDto.getOriginalLanguage()===========================" + tmdbDto.getOriginalLanguage());
            MovieDto movieDto = MovieDto.builder()
                            .movieId(newMovieId)
                            .movieKoNm(movieKoNm)
                            .movieEnNm(movieEnNm != null ? movieEnNm : "")
                            .moviePrDt(moviePrDt)
                            .movieRuntime(movieRuntime)
                            .movieOpenDt(movieOpenDt)  // null일 수 있음
                            .movieWarchGrd(grade)
                            .moviePlot(plotText)
                            .movieAwards(String.join(",", awards))
                            .showTypeCd(kmdbDto != null && kmdbDto.getUse() != null ? kmdbDto.getUse() : "")
                            .prdtStat(kobisDto != null && kobisDto.getPrdtStatNm() != null ? kobisDto.getPrdtStatNm() : "")
                            .showTypes(kobisDto != null && kobisDto.getTypeNm() != null ? kobisDto.getTypeNm() : "")
                            .genre(genre)
                            .showTypeGrp(kmdbDto != null && kmdbDto.getUse() != null ? kmdbDto.getUse() : "")
                            .showType(kmdbDto != null && kmdbDto.getType() != null ? kmdbDto.getType() : "")
                            .watchGrade(kmdbDto != null && kmdbDto.getRating() != null ? kmdbDto.getRating() : "")
                            .episodes(kmdbDto != null && kmdbDto.getEpisodes() != null ? kmdbDto.getEpisodes() : "")
                            .ratedYn(kmdbDto != null && kmdbDto.getRatedYn() != null ? kmdbDto.getRatedYn() : "")
                            .repRatDate(kmdbDto != null && kmdbDto.getRepRatDate() != null ? kmdbDto.getRepRatDate() : "")
                            .ratingMain(kmdbDto != null && kmdbDto.getRatingMain() != null ? kmdbDto.getRatingMain() : "")
                            .keywords(kmdbDto != null && kmdbDto.getKeywords() != null ? kmdbDto.getKeywords() : "")
                            .filmingLocation(kmdbDto != null && kmdbDto.getFLocation() != null ? kmdbDto.getFLocation() : "")
                            .countryCd(tmdbDto != null ? tmdbDto.getOriginalLanguage() : "")
                            .movieLanguage(tmdbDto != null ? tmdbDto.getOriginalLanguage() : "")
                            .build();
    
            movieMapper.insertMovieInfo(movieDto);
            System.out.println("Successfully inserted movie: " + movieKoNm + " (ID: " + newMovieId + ")");
            return movieDto;
            
        } catch (Exception e) {
            System.err.println("Error creating MovieDto: " + e.getMessage());
            e.printStackTrace();
            return null;
        }
    }
    
    /**
     * 파일 다운로드, TMDB 상세 정보, 출연진 정보 등 추가 데이터 처리
     */
    private void processAdditionalData(MovieDto movieDto, KmdbDto kmdbDto, TmdbMovieSearchResult tmdbResult,
                                    ObjectMapper objectMapper, JSONParser parser) {
        try {
            // 1. KMDB 파일 다운로드 (포스터, 스틸컷, VOD)
            if (kmdbDto != null) {
                processMovieFiles(movieDto, kmdbDto);
            }
            
            // 2. TMDB 상세 정보 처리 (제작사, 출연진, 스태프)
            if (tmdbResult != null) {
                processTmdbDetails(movieDto, tmdbResult.getId(), objectMapper, parser);
                processTmdbCredits(movieDto, tmdbResult.getId(), objectMapper);
            }
            
            // 3. Spotify OST 정보
            if (movieDto.getMovieEnNm() != null && !movieDto.getMovieEnNm().isEmpty()) {
                processSpotifyOst(movieDto);
            }
            
        } catch (Exception e) {
            System.err.println("Error processing additional data for movie: " + movieDto.getMovieKoNm());
            e.printStackTrace();
        }
    }
    
    // Helper methods
    private void cleanKmdbTitle(KmdbDto dto) {
        String title = dto.getTitle();
        if (title != null) {
            String cleaned = title
                    .replaceAll(" !HS ", "")
                    .replaceAll(" !HE ", "")
                    .replaceAll("^\\s+|\\s+$", "")
                    .replaceAll(" +", " ")
                    .replaceAll("(\\D)\\s+(\\d)", "$1$2");
            dto.setTitle(cleaned);
        }
    }
    
    private boolean isTitleSimilar(String title1, String title2) {
        if (title1 == null || title2 == null) return false;
        
        String cleaned1 = title1.toLowerCase().replaceAll("[^a-zA-Z가-힣0-9]", "");
        String cleaned2 = title2.toLowerCase().replaceAll("[^a-zA-Z가-힣0-9]", "");
        
        return cleaned1.equals(cleaned2) || cleaned1.contains(cleaned2) || cleaned2.contains(cleaned1);
    }
    
    private boolean isDateMatching(String date1, String date2) {
        if (date1 == null || date2 == null) return false;
        
        String formattedDate1 = formatDate(date1);
        String formattedDate2 = formatDate(date2);
        
        return formattedDate1.equals(formattedDate2);
    }
    
    private String formatDate(String date) {
        if (date == null || date.length() < 8) return date;
        
        if (date.length() == 8 && date.matches("\\d{8}")) {
            return date.substring(0, 4) + "-" + date.substring(4, 6) + "-" + date.substring(6, 8);
        }
        
        return date;
    }
    
    // TMDB 검색 결과를 위한 간단한 데이터 클래스
    private static class TmdbMovieSearchResult {
        private String id;
        private String title;
        private String originalTitle;
        private String releaseDate;
        private String originalLanguage;
        
        // getters and setters
        public String getId() { return id; }
        public void setId(String id) { this.id = id; }
        public String getTitle() { return title; }
        public void setTitle(String title) { this.title = title; }
        public String getOriginalTitle() { return originalTitle; }
        public void setOriginalTitle(String originalTitle) { this.originalTitle = originalTitle; }
        public String getReleaseDate() { return releaseDate; }
        public void setReleaseDate(String releaseDate) { this.releaseDate = releaseDate; }
        public String getOriginalLanguage() { return originalLanguage; }
        public void setOriginalLanguage(String originalLanguage) { this.originalLanguage = originalLanguage; }
    }
    
    // 기존의 파일 처리, TMDB 상세 정보 처리, 출연진 처리 메서드들은 그대로 유지
    private void processMovieFiles(MovieDto movieDto, KmdbDto kmdbDto) {
        // 기존 코드와 동일
        if (kmdbDto == null) return;
        
        try {
            // 포스터 처리
            String posters = kmdbDto.getStlls();
            processImageFiles(movieDto, posters, "poster", "001");
            
            // 스틸컷 처리
            String stills = kmdbDto.getStlls();
            processImageFiles(movieDto, stills, "stills", "002");
            
            // VOD 처리
            if (kmdbDto.getVods() != null && kmdbDto.getVods().getVod() != null) {
                List<HashMap<String, String>> vods = kmdbDto.getVods().getVod().stream()
                    .map(v -> {
                        HashMap<String, String> map = new HashMap<>();
                        map.put("vodClass", v.getVodClass());
                        map.put("vodUrl", v.getVodUrl());
                        return map;
                    })
                    .collect(Collectors.toList());
                
                processVodFiles(movieDto, vods);
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
    
    private void processImageFiles(MovieDto movieDto, String imageUrls, String folderName, String fileTypCd) {
        if (imageUrls == null || imageUrls.isEmpty()) return;
        
        try {
            List<MovieDto> movieDtoImgList = new ArrayList<>();
            List<String> imageList = Arrays.asList(imageUrls.split("\\|"));
            
            for (String imageUrl : imageList) {
                MovieDto movieDtoImg = new MovieDto();
                String fileExtension = CommonUtil.getExtension(imageUrl);
                String fileName = CommonUtil.generateFileName(fileExtension);
                String fPath = localFilePath + filePath + "/" + folderName; 
                CommonUtil.fileDownloader(imageUrl, fPath, fileName);
                
                movieDtoImg.setMovieId(movieDto.getMovieId());
                movieDtoImg.setFilePath(fPath + "/" + fileName);
                movieDtoImg.setFileTypCd(fileTypCd);
                int fileId = movieMapper.getFileId();
                movieDtoImg.setFileId(fileId);
                movieDtoImgList.add(movieDtoImg);
            }
            
            if (!movieDtoImgList.isEmpty()) {
                movieService.insertFileInfo(movieDtoImgList);
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    /**
     * VOD URL을 처리하여 실제 다운로드 가능한 URL로 변환
     */
    private String processVodUrl(String vodUrl) {
        if (vodUrl == null || vodUrl.trim().isEmpty()) {
            return null;
        }
        
        try {
            // KMDB 트레일러 URL 패턴 처리
            if (vodUrl.contains("kmdb.or.kr/trailer/trailerPlayPop")) {
                String processedUrl = vodUrl.replaceAll(
                    "https://www\\.kmdb\\.or\\.kr/trailer/trailerPlayPop\\?pFileNm=(.+)", 
                    "https://www.kmdb.or.kr/trailer/play/$1"
                );
                
                // 변환이 제대로 되었는지 확인
                if (!processedUrl.equals(vodUrl)) {
                    System.out.println("VOD URL 변환: " + vodUrl + " -> " + processedUrl);
                    return processedUrl;
                }
            }
            
            // 이미 올바른 형식의 URL인 경우 그대로 반환
            if (vodUrl.startsWith("http://") || vodUrl.startsWith("https://")) {
                return vodUrl;
            }
            
            // 프로토콜이 없는 경우 https 추가
            if (vodUrl.startsWith("//")) {
                return "https:" + vodUrl;
            }
            
            // 그 외의 경우 null 반환 (처리 불가능한 URL)
            System.out.println("처리할 수 없는 VOD URL 형식: " + vodUrl);
            return null;
            
        } catch (Exception e) {
            System.err.println("VOD URL 처리 중 오류: " + vodUrl + " - " + e.getMessage());
            return null;
        }
    }
    
    private void processVodFiles(MovieDto movieDto, List<HashMap<String, String>> vods) {
        try {
            List<MovieDto> movieDtoVodList = new ArrayList<>();
            
            for (HashMap<String, String> vod : vods) {
                String vodUrl = vod.get("vodUrl");
                
                // URL 유효성 검사 및 전처리
                if (vodUrl == null || vodUrl.trim().isEmpty()) {
                    System.out.println("VOD URL이 비어있습니다. 건너뜁니다.");
                    continue;
                }
                
                // URL 정리 및 변환
                String originalUrl = processVodUrl(vodUrl);
                
                // 변환된 URL이 유효한지 확인
                if (originalUrl == null || originalUrl.trim().isEmpty()) {
                    System.out.println("VOD URL 변환 실패: " + vodUrl);
                    continue;
                }
                
                // URL이 올바른 프로토콜을 가지고 있는지 확인
                if (!originalUrl.startsWith("http://") && !originalUrl.startsWith("https://")) {
                    System.out.println("잘못된 VOD URL 프로토콜: " + originalUrl);
                    continue;
                }
                
                try {
                    MovieDto movieDtoVod = new MovieDto();
                    String fileExtension = CommonUtil.getExtension(originalUrl);
                    String fileName = CommonUtil.generateFileName(fileExtension);
                    String fPath = localFilePath + filePath + "/vods"; 
                    
                    // 파일 다운로드 시도
                    boolean downloadSuccess = CommonUtil.vodFileDownloader(originalUrl, fPath, fileName);
                    
                    if (downloadSuccess) {
                        movieDtoVod.setMovieId(movieDto.getMovieId());
                        movieDtoVod.setFilePath(fPath + "/" + fileName);
                        movieDtoVod.setFileTypCd("003");
                        int fileId = movieMapper.getFileId();
                        movieDtoVod.setFileId(fileId);
                        movieDtoVodList.add(movieDtoVod);
                    } else {
                        System.out.println("VOD 파일 다운로드 실패: " + originalUrl);
                    }
                    
                } catch (Exception e) {
                    System.err.println("VOD 파일 처리 중 오류 발생: " + originalUrl + " - " + e.getMessage());
                    // 개별 파일 처리 실패 시 다른 파일들은 계속 처리
                    continue;
                }
            }
            
            if (!movieDtoVodList.isEmpty()) {
                movieService.insertFileInfo(movieDtoVodList);
            }
            
        } catch (Exception e) {
            System.err.println("VOD 파일 목록 처리 중 오류 발생: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private void processTmdbDetails(MovieDto movieDto, String tmMovieId, ObjectMapper objectMapper, JSONParser parser) {
        // 기존 코드와 동일
        try {
            String tmJsonDetail = tmdbMovieClient.getMovieDetails(tmMovieId, "Bearer " + tmdbKey, "en-US", "images");
            JSONObject jsonObject = (JSONObject) parser.parse(tmJsonDetail);
            TmdbDto tmdbDto = objectMapper.readValue(jsonObject.toJSONString(), TmdbDto.class);
            System.out.println("===========================tmdb json===========================" + tmdbDto.toString());

            // 제작사 정보 처리
            List<MovieDto> movieDtoPrdList = new ArrayList<>();
            List<ProductionCompany> pdCompList = tmdbDto.getProductionCompanies();
            Boolean isFile = false;
            
            for (ProductionCompany pd : pdCompList) {
                MovieDto movieDtoComp = new MovieDto();
                movieDtoComp.setProductionEnNm(pd.getName());
                movieDtoComp.setProductionCountry(pd.getOriginCountry());
                
                if (pd.getLogoPath() != null && !pd.getLogoPath().isEmpty()) {
                    isFile = true;
                    String tmImgUrl = imageBaseUrl + pd.getLogoPath();
                    String fileExtension = CommonUtil.getExtension(tmImgUrl);
                    String fileName = CommonUtil.generateFileName(fileExtension);
                    String fPath = localFilePath + filePath + "/logo"; 
                    CommonUtil.fileDownloader(tmImgUrl, fPath, fileName);
                    
                    movieDtoComp.setMovieId(movieDto.getMovieId());
                    movieDtoComp.setFilePath(fPath + "/" + fileName);
                    movieDtoComp.setFileTypCd("004");
                    int fileId = movieMapper.getFileId();
                    int productionId = movieMapper.getProductionId();
                    movieDtoComp.setProductionId(productionId);
                    movieDtoComp.setProductionLogoFileId(fileId);
                    movieDtoComp.setFileId(fileId);
                    movieDtoPrdList.add(movieDtoComp);
                } else {
                    int productionId = movieMapper.getProductionId();
                    movieDtoComp.setProductionId(productionId);
                    movieDtoPrdList.add(movieDtoComp);
                }
            }
            
            if (!movieDtoPrdList.isEmpty()) {
                if (isFile) {
                    movieService.insertFileInfo(movieDtoPrdList);
                }
                movieMapper.insertProductionInfo(movieDtoPrdList);
                movieMapper.insertMovieProductionInfo(movieDtoPrdList);
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void processTmdbCredits(MovieDto movieDto, String tmMovieId, ObjectMapper objectMapper) {
        // 기존 코드와 동일
        try {
            String tmJsonCredits = tmdbMovieClient.getMovieCredits(tmMovieId, "Bearer " + tmdbKey, "en-US");
            JsonNode creditsNode = objectMapper.readTree(tmJsonCredits);
            JsonNode castNode = creditsNode.get("cast");
            
            if (castNode != null && castNode.isArray()) {
                processCastInfo(movieDto, castNode, objectMapper);
            }

            JsonNode crewNode = creditsNode.get("crew");
            if (crewNode != null && crewNode.isArray()) {
                movieService.insertCrewsInfo(movieDto.getMovieId(), crewNode);
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void processCastInfo(MovieDto movieDto, JsonNode castNode, ObjectMapper objectMapper) {
        try {
            List<MovieDto> movieDtoCastList = new ArrayList<>();
            List<MovieDto> movieDtoCastImgList = new ArrayList<>();
            
            for (JsonNode actor : castNode) {
                MovieDto movieDtoCast = new MovieDto();
                String actorName = actor.get("name").asText();
                String character = actor.get("character").asText();
                String profilePath = actor.get("profile_path").isNull() ? null : actor.get("profile_path").asText();
                
                movieDtoCast.setCastEnNm(actorName);
                movieDtoCast.setCastDepartment(character);
                int castId = movieMapper.getCastId();
                movieDtoCast.setCastId(castId);

                // TMDB 인물 상세 정보 조회
                processCastDetails(movieDtoCast, actorName, objectMapper);
                
                movieDtoCastList.add(movieDtoCast);
                
                // 배우 프로필 이미지 처리
                if (profilePath != null && !profilePath.isEmpty()) {
                    processCastProfileImage(movieDtoCast, profilePath, movieDtoCastImgList);
                }
            }

            if (!movieDtoCastList.isEmpty()) {
                movieMapper.insertCastInfo(movieDtoCastList);
                if (!movieDtoCastImgList.isEmpty()) {
                    movieMapper.insertCastImg(movieDtoCastImgList);
                    movieService.insertFileInfo(movieDtoCastImgList);
                }
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void processCastDetails(MovieDto movieDtoCast, String actorName, ObjectMapper objectMapper) {
        try {
            String tmdbPersonSearch = tmdbMovieClient.searchPerson("Bearer " + tmdbKey, actorName, "en-US", 1);
            JsonNode personRoot = objectMapper.readTree(tmdbPersonSearch);
            JsonNode personResults = personRoot.get("results");
            
            if (personResults != null && personResults.isArray() && personResults.size() > 0) {
                JsonNode person = personResults.get(0);
                String personId = person.get("id").asText();
                
                String tmdbPersonDetail = tmdbMovieClient.getPersonDetails(personId, "Bearer " + tmdbKey, "en-US", "movie_credits,images");
                JsonNode personDetailRoot = objectMapper.readTree(tmdbPersonDetail);
                
                String castBirth = personDetailRoot.has("birthday") && !personDetailRoot.get("birthday").isNull() 
                    ? personDetailRoot.get("birthday").asText() : null;
                String castDeath = personDetailRoot.has("deathday") && !personDetailRoot.get("deathday").isNull() 
                    ? personDetailRoot.get("deathday").asText() : null;
                String castNationality = personDetailRoot.has("place_of_birth") && !personDetailRoot.get("place_of_birth").isNull() 
                    ? personDetailRoot.get("place_of_birth").asText() : null;
                
                List<String> filmography = new ArrayList<>();
                if (personDetailRoot.has("movie_credits")) {
                    JsonNode credits = personDetailRoot.get("movie_credits");
                    if (credits.has("cast")) {
                        JsonNode filmos = credits.get("cast");
                        for (JsonNode filmo : filmos) {
                            if (filmo.has("title")) {
                                filmography.add(filmo.get("title").asText());
                            }
                        }
                    }
                }
                
                movieDtoCast.setCastBirth(castBirth);
                movieDtoCast.setCastDeath(castDeath);
                movieDtoCast.setCastNationality(castNationality);
                movieDtoCast.setCastFilmography(filmography);
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void processCastProfileImage(MovieDto movieDtoCast, String profilePath, List<MovieDto> movieDtoCastImgList) {
        try {
            String profileUrl = imageBaseUrl + profilePath;
            String fileExtension = CommonUtil.getExtension(profileUrl);
            String fileName = CommonUtil.generateFileName(fileExtension);
            String fPath = localFilePath + filePath + "/cast_profile";
            CommonUtil.fileDownloader(profileUrl, fPath, fileName);
            
            movieDtoCast.setFilePath(fPath + "/" + fileName);
            movieDtoCast.setFileTypCd("005");
            int fileId = movieMapper.getFileId();
            movieDtoCast.setCastLogoFileId(fileId);
            movieDtoCast.setFileId(fileId);
            movieDtoCastImgList.add(movieDtoCast);
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void processSpotifyOst(MovieDto movieDto) {
        try {
            SpotifyDto spotifyDto = movieService.getMovieOst(movieDto.getMovieEnNm());

            if (spotifyDto != null && spotifyDto.getTracks() != null && spotifyDto.getTracks().getItems() != null) {
                List<MovieDto> movieDtoSoundImgList = new ArrayList<>();
                List<MovieDto> movieDtoSongList = new ArrayList<>();
                Set<Integer> processedAlbumIds = new HashSet<>();
                int newAlbumId = movieMapper.getAlbumId();
                
                for (SpotifyDto.Item track : spotifyDto.getTracks().getItems()) {
                   
                    int newSoundTrackId = movieMapper.getSoundtrackId();
                    if (!processedAlbumIds.contains(newAlbumId)) {
                        processedAlbumIds.add(newAlbumId);
                        
                        String albumId = track.getAlbum().getId();
                        String albumNm = track.getAlbum().getName();
                        List<SpotifyDto.Image> albumImgs = track.getAlbum().getImages();

                        // 앨범 이미지 처리
                        processAlbumImages(newAlbumId, newSoundTrackId, albumImgs, movieDtoSoundImgList);
                        
                        // 앨범 수록곡 처리
                        processAlbumTracks(movieDto.getMovieId(), newAlbumId, newSoundTrackId, albumId, albumNm, movieDtoSongList);
                    }
                }

                if (!movieDtoSoundImgList.isEmpty()) {
                    movieMapper.insertSoundtrackImg(movieDtoSoundImgList);
                    movieService.insertFileInfo(movieDtoSoundImgList);
                }
                if (!movieDtoSongList.isEmpty()) {
                    movieMapper.insertSoundtrackInfo(movieDtoSongList);
                }
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void processAlbumImages(int albumId, int soundTrackId, List<SpotifyDto.Image> albumImgs, List<MovieDto> movieDtoSoundImgList) {
        try {
            for (SpotifyDto.Image img : albumImgs) {
                MovieDto soundImgDto = new MovieDto();
                System.out.println("===========================albumId===========================" + albumId);
                soundImgDto.setAlbumId(albumId);
                int fileId = movieMapper.getFileId();
                soundImgDto.setFileId(fileId);
                soundImgDto.setAlbumFileId(fileId);
                
                String albumImgUrl = img.getUrl();
                String fileName = CommonUtil.generateFileName("jpg");
                String fPath = localFilePath + filePath + "/album_img";
                CommonUtil.fileDownloader(albumImgUrl, fPath, fileName);
                Thread.sleep(200); // 200ms 대기
                soundImgDto.setSoundtrackId(soundTrackId);
                soundImgDto.setFilePath(fPath + "/" + fileName);
                soundImgDto.setFileTypCd("007");
                soundImgDto.setImgSzWidth(img.getWidth());
                soundImgDto.setImgSzHight(img.getHeight());
                soundImgDto.setAlbumImgId(fileId);
                movieDtoSoundImgList.add(soundImgDto);
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void processAlbumTracks(int movieId, int albumId, int soundtrackId, String spotifyAlbumId, String albumNm, List<MovieDto> movieDtoSongList) {
        try {
            int limit = 20;
            SpotifyAlbumTracksDto spotifyAlbumTracksDto = movieService.getSpotifyAlbumTracks(spotifyAlbumId, limit);
            
            for (SpotifyDto.Item album : spotifyAlbumTracksDto.getItems()) {
                MovieDto soundMovieDto = new MovieDto();
                soundMovieDto.setSoundtrackId(soundtrackId);
                soundMovieDto.setAlbumId(albumId);
                soundMovieDto.setMovieId(movieId);
                soundMovieDto.setAlbumNm(albumNm);
                soundMovieDto.setDurationMs(album.getDurationMs());

                List<SpotifyDto.Artist> artists = album.getArtists();
                String artistNm = artists.stream()
                    .map(SpotifyDto.Artist::getName)
                    .collect(Collectors.joining(","));
                soundMovieDto.setArtistNm(artistNm);
                soundMovieDto.setSongNm(album.getName());
                movieDtoSongList.add(soundMovieDto);
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    @GetMapping(value = "/getMovieOst/{movieNm}", produces = "application/json")
    public SpotifyDto getMovieOst(@PathVariable("movieNm") String movieNm) {
        try {
            // Spotify 액세스 토큰 가져오기
            String accessToken = getSpotifyAccessToken();
            
            // 영화 OST 검색
            String query = movieNm + " soundtrack";
            String jsonResponse = spotifyClient.searchTracks(
                "Bearer " + accessToken,
                query,
                "track",
                10
            );
            
            ObjectMapper objectMapper = new ObjectMapper();
            return objectMapper.readValue(jsonResponse, SpotifyDto.class);
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    private String getSpotifyAccessToken() throws Exception {
        String credentials = spotifyClientId + ":" + spotifyClientSecret;
        String encodedCredentials = Base64.getEncoder().encodeToString(credentials.getBytes());
        
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Basic " + encodedCredentials);
        headers.setContentType(MediaType.APPLICATION_FORM_URLENCODED);
        
        String body = "grant_type=client_credentials";
        
        HttpEntity<String> request = new HttpEntity<>(body, headers);
        
        RestTemplate restTemplate = new RestTemplate();
        ResponseEntity<String> response = restTemplate.postForEntity(
            "https://accounts.spotify.com/api/token",
            request,
            String.class
        );
        
        ObjectMapper objectMapper = new ObjectMapper();
        JsonNode root = objectMapper.readTree(response.getBody());
        return root.get("access_token").asText();
    }

    @GetMapping(value = "/getSpotifyAlbumTracks/{albumId}", produces = "application/json")
    public SpotifyAlbumTracksDto getSpotifyAlbumTracks(@PathVariable("albumId") String albumId, @RequestParam(value = "limit", defaultValue = "20") int limit) {
        SpotifyAlbumTracksDto spotifyDto = movieService.getSpotifyAlbumTracks(albumId, limit);
        System.out.println(spotifyDto.toString());

        return spotifyDto;
    }

    private List<MovieDto> searchMovieByName(String movieName) throws Exception {
        List<MovieDto> resultList = new ArrayList<>();
        try {
            // 유연한 검색 (여러 필드)
            //List<MovieDto> results2 = searchService.searchMoviesFlexible("spider");
            List<MovieDto> moviesFlexibleList = movieService.searchMoviesFlexible(movieName);
            System.out.println("유연한 검색 결과: " + moviesFlexibleList);
            
            // 유사도 기반 검색
            //List<MovieDto> results3 = searchService.searchMoviesWithSimilarity("아이언맨", 0.6);
            List<MovieDto> moviesWithSimilarityList = movieService.searchMoviesWithSimilarity(movieName, 0.6);
            System.out.println("유사도 검색 결과: " + moviesWithSimilarityList);
            

            resultList.addAll(moviesFlexibleList);
            resultList.addAll(moviesWithSimilarityList);
        } catch (Exception e) {
            e.printStackTrace();
        }

        return resultList;
    }

}
