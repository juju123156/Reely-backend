package com.reely.service;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.reely.dto.KobisDto;

@FeignClient(name="KobisMovieClient", url="http://kobis.or.kr/kobisopenapi/webservice/rest")
public interface KobisMovieFeignClient {
    // @GetMapping("")
    // KmdbDto kmdbDto(@RequestBody );

    @GetMapping("/movie/searchMovieList.json")
    String getMovieInfo(@RequestParam("key") String key, @RequestParam("movieNm") String movieNm);

    @GetMapping("/boxoffice/searchDailyBoxOfficeList.json")
    String getDailyBoxOfficeList(@RequestParam("key") String key, @RequestParam("targetDt") String targetDt, @RequestParam("repNationCd") String repNationCd);
}
