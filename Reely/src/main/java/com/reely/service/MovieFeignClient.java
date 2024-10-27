package com.reely.service;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.reely.dto.KobisDto;

@FeignClient(name="MovieClient", url="http://kobis.or.kr/kobisopenapi/webservice/rest/movie")
public interface MovieFeignClient {
    // @GetMapping("")
    // KmdbDto kmdbDto(@RequestBody );
    String KobisKey = "";
    String movieNm="기생충";
    
    @GetMapping("/searchMovieList.json")
    String getMovieInfo(@RequestParam("key") String key, @RequestParam("movieNm") String movieNm);
}
