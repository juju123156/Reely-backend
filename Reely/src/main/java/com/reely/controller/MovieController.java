package com.reely.controller;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.reely.dto.KobisDto;
import com.reely.service.MovieFeignClient;

@RestController
@RequestMapping("/api")
public class MovieController {
    
    private final MovieFeignClient movieFeignClient;
    
    @Autowired
    public MovieController(MovieFeignClient movieFeignClient) {
        this.movieFeignClient = movieFeignClient;
    }


        
    @GetMapping(value = "/getMovieInfo/{movieNm}" , produces = "application/json")
    public KobisDto getMovieInfo(@PathVariable("movieNm") String movieNm) {
        String kobisKey = "9eaf43c6cd0bde9c0862c1c2c1e4b434"; 
        String jsonData = movieFeignClient.getMovieInfo(kobisKey, movieNm);

        //ObjectMapper objectMapper = new ObjectMapper();

        // JSON 데이터 파싱
        
        KobisDto kobisDto = new KobisDto(); 
        JSONParser parser = new JSONParser();

        try {
            //kobisDto = objectMapper.readValue(jsonData.get("movieListResult"), KobisDto.class);
            // kobisDto.setMovieCd((String) jsonObject.get("movieCd"));
            // kobisDto.setMovieNm((String) jsonObject.get("movieNm"));
            System.out.println(kobisDto.toString());
            
        } catch (Exception e) {
            e.printStackTrace();
        }

        return kobisDto;
    }
}
