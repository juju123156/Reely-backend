package com.reely.serviceImpl;

import java.util.Base64;

import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.reely.dto.MovieDto;
import com.reely.dto.SpotifyDto;
import com.reely.dto.SpotifyDto.SpotifyAlbumTracksDto;
import com.reely.mapper.MovieMapper;
import com.reely.service.KmdbMovieFeignClient;
import com.reely.service.KobisMovieFeignClient;
import com.reely.service.SpotifyFeignClient;
import com.reely.service.TmdbMovieFeignClient;
import com.reely.service.MovieService;

@Service
public class MovieServiceImpl implements MovieService {
    
    private final KobisMovieFeignClient kobisFeignClient;
    private final KmdbMovieFeignClient kmdbFeignClient;
    private final TmdbMovieFeignClient tmdbMovieClient;
    private final SpotifyFeignClient spotifyClient;
    // tmdb 이미지 url
    private static final String imageBaseUrl = "https://image.tmdb.org/t/p/original";
    private final MovieMapper movieMapper;

    String kobisKey = "9eaf43c6cd0bde9c0862c1c2c1e4b434"; 
    String kmdbKey = "MZ53N9719N5IH6Z7G2R9";
    String tmdbKey = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI5MWJlODU2OGFhYzg4OGMyMzYxOTliMjBmNTBiZWFhNiIsIm5iZiI6MTc0NDYxNzA1Ni43NjQsInN1YiI6IjY3ZmNiZTYwZWMyMmJhM2I0OWQ5ODg0YyIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.SH_t-hN5ptu6cBiLvpK0DSU0U56ZKWwaXUIchYFkMQM";
    String spotifyClientId = "5b2c9e587cf74849aa331f4c8cf79a9f";
    String spotifyClientSecret = "4ccb21a2472048c69fe4741655125741";

    public MovieServiceImpl(MovieMapper movieMapper, KobisMovieFeignClient kobisFeignClient, KmdbMovieFeignClient kmdbFeignClient, TmdbMovieFeignClient tmdbFeignClient, SpotifyFeignClient spotifyClient) {
        this.movieMapper = movieMapper;
        this.kobisFeignClient = kobisFeignClient;
        this.kmdbFeignClient = kmdbFeignClient;
        this.tmdbMovieClient = tmdbFeignClient;
        this.spotifyClient = spotifyClient;
    }

    @Override
    public SpotifyDto getMovieOst(String movieNm) {
        try {
            // Spotify 액세스 토큰 가져오기
            String accessToken = getSpotifyAccessToken();
            
            // 영화 OST 검색
            String query = movieNm + " soundtrack";
            String jsonResponse = spotifyClient.searchTracks(
                "Bearer " + accessToken,
                query,
                "track",
                10
            );
            
            ObjectMapper objectMapper = new ObjectMapper();
            SpotifyDto spotifyDto = objectMapper.readValue(jsonResponse, SpotifyDto.class);
            return spotifyDto;
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    @Override
    public SpotifyAlbumTracksDto getSpotifyAlbumTracks(String albumId, int limit) {
        try {
            String accessToken = getSpotifyAccessToken();
            String jsonResponse = spotifyClient.getAlbumTracks(
                "Bearer " + accessToken,
                albumId,
                limit
            );
            ObjectMapper objectMapper = new ObjectMapper();
            SpotifyAlbumTracksDto spotifyDto = objectMapper.readValue(jsonResponse, SpotifyAlbumTracksDto.class);
            return spotifyDto;
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    private String getSpotifyAccessToken() throws Exception {
        String credentials = spotifyClientId + ":" + spotifyClientSecret;
        String encodedCredentials = Base64.getEncoder().encodeToString(credentials.getBytes());
        
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Basic " + encodedCredentials);
        headers.setContentType(MediaType.APPLICATION_FORM_URLENCODED);
        
        String body = "grant_type=client_credentials";
        
        HttpEntity<String> request = new HttpEntity<>(body, headers);
        
        RestTemplate restTemplate = new RestTemplate();
        ResponseEntity<String> response = restTemplate.postForEntity(
            "https://accounts.spotify.com/api/token",
            request,
            String.class
        );
        
        ObjectMapper objectMapper = new ObjectMapper();
        JsonNode root = objectMapper.readTree(response.getBody());
        return root.get("access_token").asText();
    }

    @Override
    public int insertFileInfo(List<MovieDto>  movieDto) {
        return movieMapper.insertFileInfo(movieDto);
    }
}