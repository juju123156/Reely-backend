package com.reely.controller;

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

import com.reely.dto.KobisDto;
import com.reely.service.KmdbMovieFeignClient;
import com.reely.service.KobisMovieFeignClient;

@RestController
@RequestMapping("/api")
public class MovieController {
    
    private final KobisMovieFeignClient kobisFeignClient;
    private final KmdbMovieFeignClient kmdbFeignClient;

    @Autowired
    public MovieController(KobisMovieFeignClient kobisFeignClient, KmdbMovieFeignClient kmdbFeignClient) {
        this.kobisFeignClient = kobisFeignClient;
        this.kmdbFeignClient= kmdbFeignClient;
    }

    


        
    @GetMapping(value = "/getMovieInfo/{movieNm}" , produces = "application/json")
    public KobisDto getMovieInfo(@PathVariable("movieNm") String movieNm) {
        String kobisKey = "9eaf43c6cd0bde9c0862c1c2c1e4b434"; 
        String kmdbKey = "MZ53N9719N5IH6Z7G2R9";
        String jsonData = kobisFeignClient.getMovieInfo(kobisKey, movieNm);
        //System.out.println(jsonData);
        System.out.println("--------------------------------------------------------------");
        //ObjectMapper objectMapper = new ObjectMapper();

        // JSON 데이터 파싱
        
        KobisDto kobisDto = new KobisDto(); 
        JSONParser parser = new JSONParser();

        try {
            JSONObject jsonObject = (JSONObject) parser.parse(jsonData);
            JSONObject movieListResult = (JSONObject) jsonObject.get("movieListResult");
            JSONArray movieList = (JSONArray) movieListResult.get("movieList");
            JSONObject movie = (JSONObject) movieList.get(0);
            kobisDto.setMovieCd((String) movie.get("movieCd"));
            kobisDto.setMovieNm((String) movie.get("movieNm"));
            kobisDto.setMovieNmEn((String) movie.get("movieNmEn"));
            kobisDto.setMovieNmOg((String) movie.get("movieNmOg"));
            kobisDto.setPrdtYear((String) movie.get("prdtYear"));
            kobisDto.setShowTm((String) movie.get("showTm"));
            kobisDto.setOpenDt((String) movie.get("openDt"));
            kobisDto.setPrdtStatNm((String) movie.get("prdtStatNm"));
            kobisDto.setTypeNm((String) movie.get("typeNm"));
            kobisDto.setNationAlt((String) movie.get("nationAlt"));
            kobisDto.setGenreAlt((String) movie.get("genreAlt"));
            kobisDto.setDirectors((List<Map<String, String>>) movie.get("directors"));
            kobisDto.setActors((List<Map<String, String>>) movie.get("actors"));
            kobisDto.setCast((List<Map<String, String>>) movie.get("cast"));
            kobisDto.setCastEn((List<Map<String, String>>) movie.get("castEn"));
            kobisDto.setShowTypes((String) movie.get("showTypes"));
            kobisDto.setShowTypeGroupNm((String) movie.get("showTypeGroupNm"));
            kobisDto.setShowTypeNm((String) movie.get("showTypeNm"));
            kobisDto.setAudits((List<Map<String, String>>) movie.get("audits"));
            kobisDto.setAuditNo((String) movie.get("auditNo"));
            kobisDto.setWatchGradeNm((String) movie.get("watchGradeNm"));
            kobisDto.setCompanys((List<Map<String, String>>) movie.get("companys"));
            kobisDto.setCompanyCd((String) movie.get("companyCd"));
            kobisDto.setCompanyNm((String) movie.get("companyNm"));
            kobisDto.setCompanyNmEn((String) movie.get("companyNmEn"));
            kobisDto.setCompanyPartNm((String) movie.get("companyPartNm"));
            kobisDto.setStaffs((List<Map<String, String>>) movie.get("staffs"));
            kobisDto.setStaffRoleNm((String) movie.get("staffRoleNm"));
            kobisDto.setDirectorNm((String) movie.get("directorNm"));
            kobisDto.setOpenStartDt((String) movie.get("openStartDt"));
            kobisDto.setOpenEndDt((String) movie.get("openEndDt"));
            kobisDto.setPrdtStartYear((String) movie.get("prdtStartYear"));
            kobisDto.setPrdtEndYear((String) movie.get("prdtEndYear"));
            kobisDto.setRepNationCd((String) movie.get("repNationCd"));
            kobisDto.setRepNationNm((String) movie.get("repNationNm"));
            kobisDto.setRepGenreNm((String) movie.get("repGenreNm"));
            kobisDto.setMovieTypeCd((String) movie.get("movieTypeCd"));
            
            //System.out.println(kobisDto.toString());
            

            String kmJsonData = kmdbFeignClient.getMovieInfo(kmdbKey, movieNm);
            System.out.println(kmJsonData);
        } catch (Exception e) {
            e.printStackTrace();
        }

        return kobisDto;
    }
}
