package com.reely.service;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.reely.dto.KobisDto;

@FeignClient(name="KmdbMovieClient", url="http://api.koreafilm.or.kr/openapi-data2/wisenut/search_api")
public interface KmdbMovieFeignClient {

    @GetMapping("/search_json2.jsp?collection=kmdb_new2&detail=Y&listCount=10")
    String getMovieInfo(@RequestParam("ServiceKey") String ServiceKey, @RequestParam("title") String title);
}

