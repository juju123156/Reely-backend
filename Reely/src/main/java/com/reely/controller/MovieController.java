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

        String jsonData = kobisFeignClient.getMovieInfo(kobisKey, movieNm);
        //System.out.println(jsonData);
        
        ObjectMapper objectMapper = new ObjectMapper();

        // JSON 데이터 파싱
        
        KobisDto kobisDto = new KobisDto();
        KmdbDto kmdbDto = new KmdbDto();
        JSONParser parser = new JSONParser();

        try {
            JSONObject jsonObject = (JSONObject) parser.parse(jsonData);
            JSONObject movieListResult = (JSONObject) jsonObject.get("movieListResult");
            JSONArray movieList = (JSONArray) movieListResult.get("movieList");
            JSONObject movie = (JSONObject) movieList.get(0);
            kobisDto = objectMapper.readValue(movie.toJSONString(), KobisDto.class);
            //System.out.println(movie.toJSONString());
            //System.out.println("--------------------------------------------------------------");
            //System.out.println(kobisDto.toString());
            

            String kmJsonData = kmdbFeignClient.getMovieInfo(kmdbKey, movieNm);
            //System.out.println(kmJsonData);
            System.out.println(kmJsonData);
            JsonNode root = objectMapper.readTree(kmJsonData);
        
            // Data 배열의 첫 번째 요소를 가져옴
            JsonNode dataArray = root.path("Data");
            if (dataArray.isArray() && dataArray.size() > 0) {
                JsonNode firstData = dataArray.get(0);
                JsonNode resultArray = firstData.path("Result");
                List<KmdbDto> kmdbList = objectMapper.readerForListOf(KmdbDto.class).readValue(resultArray);
                String kmdbListStr = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(kmdbList);
                System.out.println(kmdbListStr);
                System.out.println("--------------------------------------------------------------");
                System.out.println(resultArray.toString());
            }
            
            //System.out.println(movieListKm.toJSONString());
           
            //System.out.println(kmdbDto.toString());
            //System.out.println("2--------------------------------------------------------------");
            
            
        } catch (Exception e) {
            e.printStackTrace();
        }

        return kobisDto;
    }
}
