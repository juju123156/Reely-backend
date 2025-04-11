package com.reely.controller;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

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
    public KobisDto getMovieInfo(@PathVariable("movieNm") String movieNm) {
        ObjectMapper objectMapper = new ObjectMapper();
        KobisDto kobisDto = new KobisDto();
        KmdbDto kmdbDto = new KmdbDto();
        JSONParser parser = new JSONParser();
        MovieDto movieDto = new MovieDto();

        String jsonData = kobisFeignClient.getMovieInfo(kobisKey, movieNm);

        try {
            JSONObject jsonObject = (JSONObject) parser.parse(jsonData);
            JSONObject movieListResult = (JSONObject) jsonObject.get("movieListResult");
            JSONArray movieList = (JSONArray) movieListResult.get("movieList");
            JSONObject movie = (JSONObject) movieList.get(0);
            kobisDto = objectMapper.readValue(movie.toJSONString(), KobisDto.class);

            String kmJsonData = kmdbFeignClient.getMovieInfo(kmdbKey, movieNm);
            JsonNode root = objectMapper.readTree(kmJsonData);
            // Data 배열의 첫 번째 요소를 가져옴
            JsonNode dataArray = root.path("Data");
            if (dataArray.isArray() && dataArray.size() > 0) {
                JsonNode firstData = dataArray.get(0);
                JsonNode resultArray = firstData.path("Result");
                List<KmdbDto> kmdbList = objectMapper.readerForListOf(KmdbDto.class).readValue(resultArray);
                
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
                movieDto.setMovieId("MV12345");
                movieDto.setMovieKoNm("겨울왕국");
                movieDto.setMovieEnNm("Frozen");
                movieDto.setMoviePrDt("2013");
                movieDto.setMovieRuntime(108);
                movieDto.setMovieOpenDt(LocalDate.of(2014, 1, 16));
                movieDto.setMovieAutids("Chris Buck, Jennifer Lee");

                // 감독 이름 리스트
                Map<String, String> director1 = Map.of("directorNm", "크리스 벅", "directorEnNm", "Chris Buck");
                Map<String, String> director2 = Map.of("directorNm", "제니퍼 리", "directorEnNm", "Jennifer Lee");
                movieDto.setMovieAutidsList(Arrays.asList(director1, director2));

                movieDto.setMovieAutidsNo("0001,0002");
                movieDto.setMovieWarchGrd("전체관람가");
                movieDto.setMoviePlot("얼어붙은 왕국을 구하기 위한 자매의 모험");
                movieDto.setMovieAudienceCnt(10000000L);
                movieDto.setMovieLanguage("영어");
                movieDto.setMovieAwards(List.of(Map.of("award", "아카데미 주제가상")));

                movieDto.setShowTypeCd("ST001");
                movieDto.setMovieTypeCd("MT001");
                movieDto.setCastId(12345L);
                movieDto.setCastNm("이디나 멘젤");
                movieDto.setCastKoNm("이디나 멘젤");
                movieDto.setCastEnNm("Idina Menzel");
                movieDto.setRoleKoNm("엘사");
                movieDto.setRoleEnNm("Elsa");
                movieDto.setCastKBirth("1971-05-30");
                movieDto.setCastDeath(null);

                movieDto.setFileId(999L);
                movieDto.setMovieImgId(111L);
                movieDto.setImgType(1L);

                movieDto.setCrewId(888L);
                movieDto.setCrewKoNm("제니퍼 리");
                movieDto.setCrewEnNm("Jennifer Lee");
                movieDto.setCrewRole("감독");
                movieDto.setCrewBirth("1971-10-22");
                movieDto.setCrewDeath(null);
                movieDto.setCrewDirectorYn("Y");

                movieDto.setCountryId(1L);
                movieDto.setCountryCd(840L);
                movieDto.setCountryNm(1L);
                movieDto.setOriginalCountryYn("Y");

                movieDto.setGroComCd("GRC001");
                movieDto.setComCd("COM001");

                movieDto.setProductionId(10L);
                movieDto.setProductionKoNm("디즈니 애니메이션 스튜디오");
                movieDto.setProductionEnNm("Walt Disney Animation Studios");
                movieDto.setMovieSearchId(10L);
                movieDto.setSoundTrackId(1010L);
                // Kobis
                movieDto.setPrdtStatNm("개봉");
                movieDto.setTypeNm("장편 애니메이션");
                movieDto.setGenreAlt("판타지, 어드벤처");

                movieDto.setActors(List.of(
                    Map.of("actorNm", "조쉬 개드", "actorEnNm", "Josh Gad")
                ));

                movieDto.setShowTypes("2D");
                movieDto.setShowTypeGroupNm("디지털");
                movieDto.setShowTypeNm("일반");
                movieDto.setWatchGradeNm("전체관람가");
                movieDto.setCompanyPartNm("제작");

                // 박스오피스
                movieDto.setBoxofficeType("일별 박스오피스");
                movieDto.setShowRange("20240406-20240406");
                movieDto.setRnum("1");
                movieDto.setRank("1");
                movieDto.setRankInten("0");
                movieDto.setRankOldAndNew("OLD");
                movieDto.setSalesAmt("123456789");
                movieDto.setSalesShare("35.6");
                movieDto.setSalesInten("5000000");
                movieDto.setSalesChange("4.3");
                movieDto.setSalesAcc("500000000");
                movieDto.setAudiCnt("25000");
                movieDto.setAudiInten("2000");
                movieDto.setAudiChange("8.7");
                movieDto.setAudiAcc("1000000");
            }
            if(kmdbDto != null){
                // Kmdb
                movieDto.setEpisodes("1");
                movieDto.setRatedYn("Y");
                movieDto.setRepRatDate("20131207");
                movieDto.setRatingMain("Y");
                movieDto.setKeywords("겨울, 자매, 얼음, 노래");
                movieDto.setPosterUrl("http://example.com/poster.jpg");
                movieDto.setStillUrl("http://example.com/still.jpg");
                movieDto.setStaffEtc("기타 정보");
                movieDto.setVodClass("예고편");
                movieDto.setVodUrl("http://example.com/trailer.mp4");
                movieDto.setStatDate("20240406");
                movieDto.setThemeSong("Let It Go");
                movieDto.setSoundtrack("OST");
                movieDto.setFLocation("아렌델 왕국");
            }
            
        } catch (Exception e) {
            e.printStackTrace();
        }

        return kobisDto;
    }

}
