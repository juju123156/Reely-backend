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
            System.out.println("===========================kmdb json==========================="+kmdbList.get(2));
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
                        map.put("roleGrpNm", s.getStaffRoleGroup());
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

            movieDto = MovieDto.builder()
                               .movieKoNm(kmdbDto.getTitle() != null ? kmdbDto.getTitle(): "")
                               .movieEnNm(kmdbDto.getTitleOrg() != null ? kmdbDto.getTitleOrg(): "")
                               .moviePrDt(kmdbDto.getProdYear() != null ? kmdbDto.getProdYear(): "")
                               .movieRuntime(kmdbDto.getRuntime() != null ? Integer.parseInt(kmdbDto.getRuntime()): null)
                               .movieOpenDt(kmdbDto.getRepRlsDate() != null ? kmdbDto.getRepRlsDate(): "")
                               .movieAutidsList(directors)
                               .movieWarchGrd(grade)
                               .movieOpenDt(kmdbDto.getRepRlsDate() != null ? kmdbDto.getRepRlsDate(): "")
                               .moviePlot(plotText)
                               .movieAwards(awards)
                               .showTypeCd(kmdbDto.getUse() != null ? kmdbDto.getUse(): "")
                               .actors(actors)
                               .movieAutidsList(casts)
                               .countryNm(kmdbDto.getNation() != null ? kmdbDto.getNation(): "")
                               .productionKoNm(kmdbDto.getCompany() != null ? kmdbDto.getCompany(): "")
                               .productionEnNm(kmdbDto.getPart() != null ? kmdbDto.getPart(): "")
                               .prdtStatNm(kobisDto.getPrdtStatNm() != null ? kobisDto.getPrdtStatNm(): "")
                               .typeNm(kobisDto.getTypeNm() != null ? kobisDto.getTypeNm(): "")
                               .genreAlt(kobisDto.getGenreAlt() != null ? kobisDto.getGenreAlt(): "")
                               .showTypeGroupNm(kmdbDto.getUse() != null ? kmdbDto.getUse(): "")
                               .showTypeNm(kmdbDto.getType() != null ? kmdbDto.getType(): "")
                               .watchGradeNm(kmdbDto.getRating() != null ? kmdbDto.getRating(): "")
                               .episodes(kmdbDto.getEpisodes() != null ? kmdbDto.getEpisodes(): "")
                               .ratedYn(kmdbDto.getRatedYn() != null ? kmdbDto.getRatedYn(): "")
                               .repRatDate(kmdbDto.getRepRatDate() != null ? kmdbDto.getRepRatDate(): "")
                               .ratingMain(kmdbDto.getRatingMain() != null ? kmdbDto.getRatingMain(): "")
                               .keywords(kmdbDto.getKeywords() != null ? kmdbDto.getKeywords(): "")
                               .posterUrl(kmdbDto.getPosters() != null ? kmdbDto.getPosters(): "")
                               .stillUrl(kmdbDto.getStlls() != null ? kmdbDto.getStlls(): "")
                               .vods(vods)
                               .themeSong(kmdbDto.getThemeSong() != null ? kmdbDto.getThemeSong(): "")
                               .soundtrack(kmdbDto.getSoundtrack() != null ? kmdbDto.getSoundtrack(): "")
                               .fLocation(kmdbDto.getFLocation() != null ? kmdbDto.getFLocation(): "")
                               .build();

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
            
        } catch (Exception e) {
            e.printStackTrace();            
        }

        return movieDto;
    }

}
