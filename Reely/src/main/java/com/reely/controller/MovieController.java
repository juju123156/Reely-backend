package com.reely.controller;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.reely.dto.KmdbDto;
import com.reely.dto.KobisDto;
import com.reely.dto.MovieDto;
import com.reely.service.KmdbMovieFeignClient;
import com.reely.service.KobisMovieFeignClient;

@RestController
@RequestMapping("/api")
public class MovieController {
    
    private final KobisMovieFeignClient kobisFeignClient;
    private final KmdbMovieFeignClient kmdbFeignClient;
    String kobisKey = "9eaf43c6cd0bde9c0862c1c2c1e4b434"; 
    String kmdbKey = "MZ53N9719N5IH6Z7G2R9";

    public MovieController(KobisMovieFeignClient kobisFeignClient, KmdbMovieFeignClient kmdbFeignClient) {
        this.kobisFeignClient = kobisFeignClient;
        this.kmdbFeignClient= kmdbFeignClient;
    }
    
    @GetMapping(value = "/getDailyBoxOfficeList" , produces = "application/json")
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
    public List<KmdbDto> getMovieInfo(@PathVariable("movieNm") String movieNm) {
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
            System.out.println("===========================kobis json==========================="+movie);
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
                }
            }

            if(kobisDto != null){
                //movieDto.setMovieId("MV12345");
                movieDto.setMovieKoNm(kmdbDto.getTitle());
                movieDto.setMovieEnNm(kmdbDto.getTitleOrg());
                movieDto.setMoviePrDt(kmdbDto.getProdYear());
                movieDto.setMovieRuntime(Integer.parseInt(kmdbDto.getRuntime()));
                movieDto.setMovieOpenDt(kmdbDto.getRepRlsDate());
                //movieDto.setMovieAutids("Chris Buck, Jennifer Lee");
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

                movieDto.setMovieAutidsList(directors);

                List<KmdbDto.Rating> ratingList = kmdbDto.getRatings().getRating();
                String grade = "";
                
                if (ratingList != null && !ratingList.isEmpty()) {
                    String raw = ratingList.get(0).getRatingGrade();
                    // || 기준으로 나누고, 첫 번째 값만 추출
                    grade = raw != null ? raw.split("\\|\\|")[0] : "";
                }
                movieDto.setMovieWarchGrd(grade);
                KmdbDto.PlotsWrapper plotsWrapper = kmdbDto.getPlots();

                String plotText = "";
                if (plotsWrapper != null && plotsWrapper.getPlot() != null && !plotsWrapper.getPlot().isEmpty()) {
                    plotText = plotsWrapper.getPlot().get(0).getPlotText(); // 첫 번째 plot의 내용
                }
                movieDto.setMoviePlot(plotText);
                //movieDto.setMovieAudienceCnt(10000000L);
                //movieDto.setMovieLanguage("영어");
                List<String> awards = new ArrayList<String>();
                
                if("".equals(kmdbDto.getAwards1())){
                    awards.add(kmdbDto.getAwards1());
                }
                if("".equals(kmdbDto.getAwards2())){
                    awards.add(kmdbDto.getAwards2());
                }
                
                movieDto.setMovieAwards(awards);

                movieDto.setShowTypeCd(kmdbDto.getUse());
                //movieDto.setMovieTypeCd();
                
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

                movieDto.setActors(actors);

                List<HashMap<String, String>> casts = new ArrayList<>();
                
                if (kmdbDto.getStaffs() != null && kmdbDto.getStaffs().getStaff() != null) {
                    casts = kmdbDto.getStaffs().getStaff().stream()
                        .map(s -> {
                            HashMap<String, String> map = new HashMap<>();
                            map.put("staffKoNm", s.getStaffNm());
                            map.put("staffEnNm", s.getStaffEnNm());
                            map.put("roleGrpNm", s.getStaffRoleGroup());
                            map.put("roleKoNm", s.getStaffRole());
                            map.put("staffEtc", s.getStaffEtc());
                            return map;
                        })
                        .collect(Collectors.toList());
                }

                movieDto.setMovieAutidsList(casts);

                //movieDto.setImgType(1L);

                movieDto.setCountryNm(kmdbDto.getNation());
                //movieDto.setOriginalCountryYn("Y");
                
                // 한영 구분 필요
                movieDto.setProductionKoNm(kmdbDto.getPart());
                movieDto.setProductionEnNm(kmdbDto.getPart());
                // Kobis
                movieDto.setPrdtStatNm(kobisDto.getPrdtStatNm());
                movieDto.setTypeNm(kobisDto.getTypeNm());
                movieDto.setGenreAlt(kobisDto.getGenreAlt());

                movieDto.setShowTypeGroupNm(kmdbDto.getUse());
                movieDto.setShowTypeNm(kmdbDto.getType());
                movieDto.setWatchGradeNm(kmdbDto.getRating());

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
            }
            if(kmdbDto != null){
                // Kmdb
                movieDto.setEpisodes(kmdbDto.getEpisodes());
                movieDto.setRatedYn(kmdbDto.getRatedYn());
                movieDto.setRepRatDate(kmdbDto.getRepRatDate());
                movieDto.setRatingMain(kmdbDto.getRatingMain());
                movieDto.setKeywords(kmdbDto.getKeywords());
                movieDto.setPosterUrl(kmdbDto.getPosterUrl());
                movieDto.setStillUrl(kmdbDto.getStillUrl());

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
                movieDto.setVods(vods);
                movieDto.setThemeSong(kmdbDto.getThemeSong());
                movieDto.setSoundtrack(kmdbDto.getSoundtrack());
                movieDto.setFLocation(kmdbDto.getFLocation());
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }

        return kmdbList;
    }

}
