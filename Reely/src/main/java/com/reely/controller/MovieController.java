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

    @GetMapping(value = "/getMovieInfo/{movieNm}" , produces = "application/json")
    public MovieDto getMovieInfo(@PathVariable("movieNm") String movieNm) {
        ObjectMapper objectMapper = new ObjectMapper();
        KobisDto kobisDto = new KobisDto();
        KmdbDto kmdbDto = new KmdbDto();
        JSONParser parser = new JSONParser();
        MovieDto movieDto = new MovieDto();
        List<KmdbDto> kmdbList = new ArrayList<>();
        String jsonData = kobisFeignClient.getMovieInfo(kobisKey, movieNm);

        try {
            JSONObject jsonObject = (JSONObject) parser.parse(jsonData);
            JSONObject movieListResult = (JSONObject) jsonObject.get("movieListResult");
            JSONArray movieList = (JSONArray) movieListResult.get("movieList");
            JSONObject movie = (JSONObject) movieList.get(0);
            kobisDto = objectMapper.readValue(movie.toJSONString(), KobisDto.class);
            String movieTitle = kobisDto.getMovieNm();
            String openDt = kobisDto.getOpenDt();
            //System.out.println("===========================kobis json==========================="+movie);
            String kmJsonData = kmdbFeignClient.getMovieInfo(kmdbKey, movieNm);
            JsonNode root = objectMapper.readTree(kmJsonData);
            // Data 배열의 첫 번째 요소를 가져옴
            JsonNode dataArray = root.path("Data");
            if (dataArray.isArray() && dataArray.size() > 0) {
                JsonNode firstData = dataArray.get(0);
                JsonNode resultArray = firstData.path("Result");
                kmdbList = objectMapper.readerForListOf(KmdbDto.class).readValue(resultArray);
                
                if (kmdbList != null) {
                    for (KmdbDto dto : kmdbList) {
                        String title = dto.getTitle();
                        if (title != null) {
                            String cleaned = title
                                    .replaceAll(" !HS ", "")
                                    .replaceAll(" !HE ", "")
                                    .replaceAll("^\\s+|\\s+$", "")  // trim
                                    .replaceAll(" +", " ")          // multiple spaces → one
                                    .replaceAll("(\\D)\\s+(\\d)", "$1$2");
                            dto.setTitle(cleaned);
                        }
                    }
                    kmdbDto = kmdbList.stream()
                    .filter(vo -> movieTitle.equals(vo.getTitle()))
                    .filter(vo -> openDt.equals(vo.getRepRlsDate()))
                    .findFirst()                // 첫 번째 요소만 뽑기
                    .orElse(null);  
                }
            // 없으면 null 리턴
            }
            //System.out.println("===========================kmdb json==========================="+kmdbList.get(2));
            List<HashMap<String, String>> directors = new ArrayList<>();
            
            if (kmdbDto.getDirectors() != null && kmdbDto.getDirectors().getDirector() != null) {
                directors = kmdbDto.getDirectors().getDirector().stream()
                    .map(d -> {
                        HashMap<String, String> map = new HashMap<>();
                        map.put("crewKoNm", d.getDirectorNm());
                        map.put("crewEnNm", d.getDirectorEnNm());
                        return map;
                    })
                    .collect(Collectors.toList());
            }

            List<KmdbDto.Rating> ratingList = new ArrayList<>();
            String grade = "";
            
            if (kmdbDto.getRatings() != null && !kmdbDto.getRatings().getRating().isEmpty()) {
                ratingList = kmdbDto.getRatings().getRating();
                String raw = ratingList.get(0).getRatingGrade();
                // || 기준으로 나누고, 첫 번째 값만 추출
                grade = raw != null ? raw.split("\\|\\|")[0] : "";
            }
            String plotText = "";
            if (kmdbDto.getPlots() != null){
                KmdbDto.PlotsWrapper plotsWrapper = kmdbDto.getPlots();

            
                if (plotsWrapper != null && plotsWrapper.getPlot() != null && !plotsWrapper.getPlot().isEmpty()) {
                    plotText = plotsWrapper.getPlot().get(0).getPlotText(); // 첫 번째 plot의 내용
                }
            }

            List<String> awards = new ArrayList<String>();
            
            if("".equals(kmdbDto.getAwards1())){
                awards.add(kmdbDto.getAwards1());
            }
            if("".equals(kmdbDto.getAwards2())){
                awards.add(kmdbDto.getAwards2());
            }

            List<HashMap<String, String>> actors = new ArrayList<>();
            
            if (kmdbDto.getActors() != null && kmdbDto.getActors().getActor() != null) {
                actors = kmdbDto.getActors().getActor().stream()
                    .map(a -> {
                        HashMap<String, String> map = new HashMap<>();
                        map.put("castKoNm", a.getActorNm());
                        map.put("castEnNm", a.getActorEnNm());
                        return map;
                    })
                    .collect(Collectors.toList());
            }

            List<HashMap<String, String>> casts = new ArrayList<>();
            
            if (kmdbDto.getStaffs() != null && kmdbDto.getStaffs().getStaff() != null) {
                casts = kmdbDto.getStaffs().getStaff().stream()
                    .map(s -> {
                        HashMap<String, String> map = new HashMap<>();
                        map.put("staffKoNm", s.getStaffNm());
                        map.put("staffEnNm", s.getStaffEnNm());
                        map.put("crewDepartment", s.getStaffRoleGroup());
                        map.put("roleKoNm", s.getStaffRole());
                        map.put("staffEtc", s.getStaffEtc());
                        return map;
                    })
                    .collect(Collectors.toList());
            }
                
            List<HashMap<String, String>> vods = new ArrayList<>();
    
            if (kmdbDto.getVods() != null && kmdbDto.getVods().getVod() != null) {
                vods = kmdbDto.getVods().getVod().stream()
                    .map(v -> {
                        HashMap<String, String> map = new HashMap<>();
                        map.put("vodClass", v.getVodClass());
                        map.put("vodUrl", v.getVodUrl());
                        return map;
                    })
                    .collect(Collectors.toList());
            }
            int newMovieId = movieMapper.getMovieId();
            movieDto = MovieDto.builder()
                               .movieId(newMovieId)
                               .movieKoNm(kmdbDto.getTitle() != null ? kmdbDto.getTitle(): "")
                               .movieEnNm(kmdbDto.getTitleOrg() != null ? kmdbDto.getTitleOrg(): "")
                               .moviePrDt(kmdbDto.getProdYear() != null ? kmdbDto.getProdYear(): "")
                               .movieRuntime(kmdbDto.getRuntime() != null ? Integer.parseInt(kmdbDto.getRuntime()): null)
                               .movieOpenDt(kmdbDto.getRepRlsDate() != null ? kmdbDto.getRepRlsDate(): "")
                               .movieWarchGrd(grade)
                               .movieOpenDt(kmdbDto.getRepRlsDate() != null ? kmdbDto.getRepRlsDate(): "")
                               .moviePlot(plotText)
                               .movieAwards(String.join(",", awards))
                               .showTypeCd(kmdbDto.getUse() != null ? kmdbDto.getUse(): "")
                               .prdtStat(kobisDto.getPrdtStatNm() != null ? kobisDto.getPrdtStatNm(): "")
                               .showTypes(kobisDto.getTypeNm() != null ? kobisDto.getTypeNm(): "")
                               .genre(kobisDto.getGenreAlt() != null ? kobisDto.getGenreAlt(): "")
                               .showTypeGrp(kmdbDto.getUse() != null ? kmdbDto.getUse(): "")
                               .showType(kmdbDto.getType() != null ? kmdbDto.getType(): "")
                               .watchGrade(kmdbDto.getRating() != null ? kmdbDto.getRating(): "")
                               .episodes(kmdbDto.getEpisodes() != null ? kmdbDto.getEpisodes(): "")
                               .ratedYn(kmdbDto.getRatedYn() != null ? kmdbDto.getRatedYn(): "")
                               .repRatDate(kmdbDto.getRepRatDate() != null ? kmdbDto.getRepRatDate(): "")
                               .ratingMain(kmdbDto.getRatingMain() != null ? kmdbDto.getRatingMain(): "")
                               .keywords(kmdbDto.getKeywords() != null ? kmdbDto.getKeywords(): "")
                               .filmingLocation(kmdbDto.getFLocation() != null ? kmdbDto.getFLocation(): "")
                               .build();

            movieMapper.insertMovieInfo(movieDto);
            //movieDto.setOriginalCountryYn("Y");
            
            // 한영 구분 필요
            //movieDto.setProductionKoNm(kmdbDto.getCompany());
            //movieDto.setProductionEnNm(kmdbDto.getPart());

            // 박스오피스
            // movieDto.setBoxofficeType("일별 박스오피스");
            // movieDto.setShowRange("20240406-20240406");
            // movieDto.setRnum("1");
            // movieDto.setRank("1");
            // movieDto.setRankInten("0");
            // movieDto.setRankOldAndNew("OLD");
            // movieDto.setSalesAmt("123456789");
            // movieDto.setSalesShare("35.6");
            // movieDto.setSalesInten("5000000");
            // movieDto.setSalesChange("4.3");
            // movieDto.setSalesAcc("500000000");
            // movieDto.setAudiCnt("25000");
            // movieDto.setAudiInten("2000");
            // movieDto.setAudiChange("8.7");
            // movieDto.setAudiAcc("1000000");

            
            String posters = movieDto.getPosterUrl();
            List<MovieDto> movieDtoPstList = new ArrayList<>();
            
            List<String> posterList = (posters == null || posters.isEmpty())
                    ? new ArrayList<>()
                    : Arrays.asList(posters.split("\\|"));
            for (int i = 0; i < posterList.size(); i++) {
                MovieDto movieDtoPst = new MovieDto();
                String posterUrl = posterList.get(i);
                String fileExtension = CommonUtil.getExtension(posterUrl);
                String fileName = CommonUtil.generateFileName(fileExtension);
                String fPath = localFilePath+filePath+"/poster"; 
                CommonUtil.fileDownloader(posterUrl, fPath, fileName);
                movieDtoPst.setMovieId(movieDto.getMovieId());
                movieDtoPst.setFilePath(fPath+"/"+fileName);
                movieDtoPst.setFileTypCd("001");
                int fileId = movieMapper.getFileId();
                movieDtoPst.setFileId(fileId);
                movieDtoPstList.add(movieDtoPst);
            }
            if(!movieDtoPstList.isEmpty()){
                movieService.insertFileInfo(movieDtoPstList);
            }

            String stills = movieDto.getStillUrl();
            List<MovieDto> movieDtoStllList = new ArrayList<>();
            
            List<String> stillsList = (stills == null || stills.isEmpty())
                    ? new ArrayList<>()
                    : Arrays.asList(stills.split("\\|"));
            for (int i = 0; i < stillsList.size(); i++) {
                MovieDto movieDtoStll = new MovieDto();
                movieDtoStll.setMovieId(movieDto.getMovieId());
                String stillsUrl = stillsList.get(i);
                String fileExtension = CommonUtil.getExtension(stillsUrl);
                String fileName = CommonUtil.generateFileName(fileExtension);
                String fPath = localFilePath+filePath+"/stills"; 
                CommonUtil.fileDownloader(stillsUrl, fPath, fileName);
                movieDtoStll.setFilePath(fPath+"/"+fileName);
                movieDtoStll.setFileTypCd("002");
                int fileId = movieMapper.getFileId();
                movieDtoStll.setFileId(fileId);
                movieDtoStllList.add(movieDtoStll);
            }
            if(!movieDtoStllList.isEmpty()){
                movieService.insertFileInfo(movieDtoStllList);
            }

            List<MovieDto> movieDtoVodList = new ArrayList<>();
            
            for (HashMap<String, String> vod : vods) {
                MovieDto movieDtoVod = new MovieDto();
                String vodUrl = vod.get("vodUrl");
                String originalUrl = vodUrl.replaceAll("https://www\\.kmdb\\.or\\.kr/trailer/trailerPlayPop\\?pFileNm=(.+)", 
                "https://www.kmdb.or.kr/trailer/play/$1");
                String fileExtension = CommonUtil.getExtension(originalUrl);
                String fileName = CommonUtil.generateFileName(fileExtension);
                String fPath = localFilePath+filePath+"/vods"; 
                //String getVodUrl = CommonUtil.extractRealMp4Url(vodUrlHtml); // 메서드 이름 수정
                //String decodedUrl = URLDecoder.decode(getVodUrl, "UTF-8");
                CommonUtil.vodFileDownloader(originalUrl, fPath, fileName);
                movieDtoVod.setMovieId(movieDto.getMovieId());
                movieDtoVod.setFilePath(fPath+"/"+fileName);
                movieDtoVod.setFileTypCd("003");
                int fileId = movieMapper.getFileId();
                movieDtoVod.setFileId(fileId);
                movieDtoVodList.add(movieDtoVod);

            }
            if(!movieDtoVodList.isEmpty()){
                movieService.insertFileInfo(movieDtoVodList);
            }
            
        } catch (Exception e) {
            e.printStackTrace();            
        }

        try {
            String tmJsonData = tmdbMovieClient.searchMovie("Bearer " + tmdbKey, movieDto.getMovieEnNm(), "en-US", 1);
            com.fasterxml.jackson.databind.JsonNode jsonNode = objectMapper.readTree(tmJsonData);
            com.fasterxml.jackson.databind.JsonNode results = jsonNode.get("results");

            com.fasterxml.jackson.databind.JsonNode item = results.get(0);
            String tmMovieId = item.get("id").asText();
            String language = item.get("original_language").asText();
            movieDto.setCountryCd(language);
            // 국가 저장
            //movieMapper.insertCountryInfo(movieDto);
            
            String tmJsonDetail = tmdbMovieClient.getMovieDetails(tmMovieId,"Bearer " + tmdbKey, "en-US", "images");
            JSONObject jsonObject = (JSONObject) parser.parse(tmJsonDetail);
            TmdbDto tmdbDto = objectMapper.readValue(jsonObject.toJSONString(), TmdbDto.class);
            System.out.println("===========================tmdb json===========================" + tmdbDto.toString());



            List<MovieDto> movieDtoPrdList = new ArrayList<>();
            List<ProductionCompany> pdCompList = tmdbDto.getProductionCompanies();
            Boolean isFile = false;
            for (ProductionCompany pd : pdCompList){
                MovieDto movieDtoComp = new MovieDto();
                movieDtoComp.setProductionEnNm(pd.getName());
                movieDtoComp.setProductionCountry(pd.getOriginCountry());
                
                // logoPath가 null이 아닌 경우에만 이미지 다운로드 시도
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
                    // logoPath가 null인 경우 기본 처리
                    int productionId = movieMapper.getProductionId();
                    movieDtoComp.setProductionId(productionId);
                    movieDtoPrdList.add(movieDtoComp);
                }
            }
            if(!movieDtoPrdList.isEmpty()){
                
                if(isFile){
                    movieService.insertFileInfo(movieDtoPrdList);
                }
                
                movieMapper.insertProductionInfo(movieDtoPrdList);
                movieMapper.insertMovieProductionInfo(movieDtoPrdList);
            }

            // 출연진 정보 조회
            String tmJsonCredits = tmdbMovieClient.getMovieCredits(tmMovieId, "Bearer " + tmdbKey, "en-US");
            JsonNode creditsNode = objectMapper.readTree(tmJsonCredits);
            JsonNode castNode = creditsNode.get("cast");

            if (castNode != null && castNode.isArray()) {
                List<MovieDto> movieDtoCastList = new ArrayList<>();
                List<MovieDto> movieDtoCastImgList = new ArrayList<>();
                for (JsonNode actor : castNode) {
                    MovieDto movieDtoCast = new MovieDto();
                    String actorName = actor.get("name").asText();
                    String character = actor.get("character").asText();
                    String profilePath = actor.get("profile_path").isNull() ? null : actor.get("profile_path").asText();
                    
                    // KMDB에서 배우 한글/영문 이름 매칭
                    String castKoNm = null;
                    String castEnNm = actorName;
                    String castBirth = null;
                    String castDeath = null;
                    String castNationality = null;
                    List<String> filmography = new ArrayList<>();
                    if (kmdbDto != null && kmdbDto.getActors() != null && kmdbDto.getActors().getActor() != null) {
                        for (KmdbDto.Actor kmdbActor : kmdbDto.getActors().getActor()) {
                            if (kmdbActor.getActorEnNm() != null && kmdbActor.getActorEnNm().equalsIgnoreCase(actorName)) {
                                castKoNm = kmdbActor.getActorNm();
                                castEnNm = kmdbActor.getActorEnNm();
                                break;
                            }
                        }
                    }
                    movieDtoCast.setCastKoNm(castKoNm);
                    movieDtoCast.setCastEnNm(castEnNm);
                    movieDtoCast.setCastDepartment(character);
                    int castId = movieMapper.getCastId();
                    movieDtoCast.setCastId(castId);

                    // TMDB 인물 검색 (영문 이름 기준)
                    try {
                        String tmdbPersonSearch = tmdbMovieClient.searchPerson("Bearer " + tmdbKey, castEnNm, "en-US", 1);
                        JsonNode personRoot = objectMapper.readTree(tmdbPersonSearch);
                        JsonNode personResults = personRoot.get("results");
                        if (personResults != null && personResults.isArray() && personResults.size() > 0) {
                            JsonNode person = personResults.get(0);
                            String personId = person.get("id").asText();
                            // 상세 정보
                            String tmdbPersonDetail = tmdbMovieClient.getPersonDetails(personId, "Bearer " + tmdbKey, "en-US", "movie_credits,images");
                            JsonNode personDetailRoot = objectMapper.readTree(tmdbPersonDetail);
                            castBirth = personDetailRoot.has("birthday") && !personDetailRoot.get("birthday").isNull() ? personDetailRoot.get("birthday").asText() : null;
                            castDeath = personDetailRoot.has("deathday") && !personDetailRoot.get("deathday").isNull() ? personDetailRoot.get("deathday").asText() : null;
                            castNationality = personDetailRoot.has("place_of_birth") && !personDetailRoot.get("place_of_birth").isNull() ? personDetailRoot.get("place_of_birth").asText() : null;
                            // filmography(출연작)
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
                        }
                    } catch (Exception e) {
                        e.printStackTrace();
                    }
                    movieDtoCast.setCastBirth(castBirth);
                    movieDtoCast.setCastDeath(castDeath);
                    movieDtoCast.setCastNationality(castNationality);
                    movieDtoCast.setCastFilmography(filmography);
                    movieDtoCastList.add(movieDtoCast);
                    // 배우 프로필 이미지 다운로드 및 저장
                    if (profilePath != null && !profilePath.isEmpty()) {
                        String profileUrl = imageBaseUrl + profilePath;
                        String fileExtension = CommonUtil.getExtension(profileUrl);
                        String fileName = CommonUtil.generateFileName(fileExtension);
                        String fPath = localFilePath + filePath + "/cast_profile";
                        CommonUtil.fileDownloader(profileUrl, fPath, fileName);
                        
                        movieDtoCast.setFilePath(fPath + "/" + fileName);
                        movieDtoCast.setFileTypCd("005"); // cast profile 이미지 타입 코드
                        int fileId = movieMapper.getFileId();
                        System.out.println("400 : "+fileId);
                        movieDtoCast.setCastLogoFileId(fileId);
                        
                        movieDtoCast.setFileId(fileId);
                        movieDtoCastImgList.add(movieDtoCast);
                    }
                }

                if(!movieDtoCastList.isEmpty()){
                     // 배우 정보 저장
                    movieMapper.insertCastInfo(movieDtoCastList);
                    // 배우 프로필 이미지 저장
                    movieMapper.insertCastImg(movieDtoCastImgList);
                    movieService.insertFileInfo(movieDtoCastImgList);
                }
            }

            JsonNode crewNode = creditsNode.get("crew");
            // if (crewNode != null && crewNode.isArray()) {

            //     List<MovieDto> movieDtoCrewList = new ArrayList<>();
            //     List<MovieDto> crewImgList = new ArrayList<>();
            //     for (JsonNode crew : crewNode) {
            //         MovieDto movieDtoCrew = new MovieDto();
            //         String crewName = crew.get("name").asText();
            //         String job = crew.get("job").asText();
            //         String department = crew.get("department").asText();
            //         String profilePath = crew.get("profile_path").isNull() ? null : crew.get("profile_path").asText();

            //         // 스태프 정보 저장
            //         movieDtoCrew.setCrewEnNm(crewName);
            //         movieDtoCrew.setCrewRole(job);
            //         movieDtoCrew.setCrewDepartment(department);

            //         // 프로필 이미지 다운로드 및 저장
            //         if (profilePath != null && !profilePath.isEmpty()) {
            //             String profileUrl = imageBaseUrl + profilePath;
            //             String fileExtension = CommonUtil.getExtension(profileUrl);
            //             String fileName = CommonUtil.generateFileName(fileExtension);
            //             String fPath = localFilePath + filePath + "/crew_profile";
            //             CommonUtil.fileDownloader(profileUrl, fPath, fileName);
                        
            //             movieDtoCrew.setFilePath(fPath + "/" + fileName);
            //             movieDtoCrew.setFileTypCd("006"); // crew profile 이미지 타입 코드
            //             int fileId = movieMapper.getFileId();
            //             System.out.println("434 : "+fileId);
            //             movieDtoCrew.setFileId(fileId);
            //             crewImgList.add(movieDtoCrew);
                        
            //         }
            //     }
            // }
        if(crewNode != null && crewNode.isArray()){
            // 스태프 정보 저장
            movieService.insertCrewsInfo(movieDto.getMovieId(), crewNode);
        }

        SpotifyDto spotifyDto = movieService.getMovieOst(movieDto.getMovieEnNm());

        if (spotifyDto != null && spotifyDto.getTracks() != null && spotifyDto.getTracks().getItems() != null) {
            List<MovieDto> movieDtoSoundImgList = new ArrayList<>();
            List<MovieDto> movieDtoSongList = new ArrayList<>();
            Set<Integer> procedAlbumIds = new HashSet<>();
            for (SpotifyDto.Item track : spotifyDto.getTracks().getItems()) {
                int newAlbumId = movieMapper.getAlbumId();
                if (!procedAlbumIds.contains(newAlbumId)) {
                    procedAlbumIds.add(newAlbumId);
                    // OST 정보 처리 로직
                    
                    String albumId = track.getAlbum().getId();
                    String albumNm = track.getAlbum().getName();
                    List<SpotifyDto.Image> albumImgs = track.getAlbum().getImages();

                    for(SpotifyDto.Image img : albumImgs){
                        MovieDto soundImgDto = new MovieDto();
                        soundImgDto.setAlbumId(newAlbumId);
                        int fileId = movieMapper.getFileId();
                        soundImgDto.setFileId(fileId);
                        soundImgDto.setAlbumFileId(fileId);
                        String albumImgUrl =  img.getUrl();
                        //String fileExtension = CommonUtil.getExtension(albumImgUrl);
                        String fileName = CommonUtil.generateFileName("jpg");
                        String fPath = localFilePath + filePath + "/album_img";
                        CommonUtil.fileDownloader(albumImgUrl, fPath, fileName);
                        Thread.sleep(200); // 200ms = 0.2초
                        soundImgDto.setFilePath(fPath + "/" + fileName);
                        soundImgDto.setFileTypCd("007");
                        soundImgDto.setImgSzWidth(img.getWidth());
                        soundImgDto.setImgSzHight(img.getWidth());
                        soundImgDto.setAlbumImgId(fileId);
                        movieDtoSoundImgList.add(soundImgDto);
                    }

                    // 앨범 수록곡 조회
                    int limit = 20;
                    SpotifyAlbumTracksDto spotifyAlbumTracksDto = movieService.getSpotifyAlbumTracks(albumId, limit);
                    
                    for (SpotifyDto.Item album : spotifyAlbumTracksDto.getItems()) {
                        MovieDto soundMovieDto = new MovieDto();
                        soundMovieDto.setAlbumId(newAlbumId);
                        soundMovieDto.setMovieId(movieDto.getMovieId());
                        soundMovieDto.setAlbumId(newAlbumId);
                        soundMovieDto.setAlbumNm(albumNm);
                        soundMovieDto.setDurationMs(album.getDurationMs());

                        List<SpotifyDto.Artist> artists = album.getArtists();
                        String artistNm = artists.stream()
                            .map(SpotifyDto.Artist::getName)
                            .collect(Collectors.joining(","));
                            soundMovieDto.setArtistNm(artistNm);
                        soundMovieDto.setArtistNm(album.getArtists().get(0).getName());
                        soundMovieDto.setSongNm(album.getName());
                        movieDtoSongList.add(soundMovieDto);
                        
                    }
                }

            }

            if(!movieDtoSoundImgList.isEmpty()){
                movieMapper.insertSoundtrackImg(movieDtoSoundImgList);
                movieService.insertFileInfo(movieDtoSoundImgList);
            }
            if(!movieDtoSongList.isEmpty()){
                movieMapper.insertSoundtrackInfo(movieDtoSongList);
            }

        }
            
        } catch(Exception e) {
            e.printStackTrace();  
        }

        return movieDto;
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

}
