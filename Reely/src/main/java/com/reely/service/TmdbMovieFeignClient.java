package com.reely.service;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;

@FeignClient(name="TmdbMovieClient", url="https://api.themoviedb.org/3")
public interface TmdbMovieFeignClient {
    
    // 영화 검색
    @GetMapping("/search/movie")
    String searchMovie(
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam("query") String query,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language,
        @RequestParam(value = "page", defaultValue = "1") int page
    );

    // 영화 상세 정보
    @GetMapping("/movie/{movie_id}")
    String getMovieDetails(
        @PathVariable("movie_id") String movieId,
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language,
        @RequestParam(value = "append_to_response", defaultValue = "videos,credits,images") String appendToResponse
    );

    // 인기 영화 목록
    @GetMapping("/movie/popular")
    String getPopularMovies(
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language,
        @RequestParam(value = "page", defaultValue = "1") int page
    );

    // 현재 상영중인 영화
    @GetMapping("/movie/now_playing")
    String getNowPlayingMovies(
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language,
        @RequestParam(value = "page", defaultValue = "1") int page
    );

    // 상영 예정 영화
    @GetMapping("/movie/upcoming")
    String getUpcomingMovies(
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language,
        @RequestParam(value = "page", defaultValue = "1") int page
    );

    // 인물 검색
    @GetMapping("/search/person")
    String searchPerson(
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam("query") String query,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language,
        @RequestParam(value = "page", defaultValue = "1") int page
    );

    // 인물 상세 정보
    @GetMapping("/person/{person_id}")
    String getPersonDetails(
        @PathVariable("person_id") String personId,
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language,
        @RequestParam(value = "append_to_response", defaultValue = "movie_credits,images") String appendToResponse
    );

    // 인물의 출연 작품
    @GetMapping("/person/{person_id}/movie_credits")
    String getPersonMovieCredits(
        @PathVariable("person_id") String personId,
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language
    );

    // 인물의 이미지
    @GetMapping("/person/{person_id}/images")
    String getPersonImages(
        @PathVariable("person_id") String personId,
        @RequestHeader("Authorization") String bearerToken
    );

    // 영화 출연진 정보
    @GetMapping("/movie/{movie_id}/credits")
    String getMovieCredits(
        @PathVariable("movie_id") String movieId,
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam(value = "language", defaultValue = "ko-KR") String language
    );
}
