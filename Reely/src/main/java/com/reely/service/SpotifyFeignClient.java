package com.reely.service;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;

@FeignClient(name = "SpotifyClient", url = "https://api.spotify.com/v1")
public interface SpotifyFeignClient {
    
    @GetMapping("/search")
    String searchTracks(
        @RequestHeader("Authorization") String bearerToken,
        @RequestParam("q") String query,
        @RequestParam("type") String type,
        @RequestParam("limit") int limit
    );

    @GetMapping("/albums/{id}/tracks")
    String getAlbumTracks(
        @RequestHeader("Authorization") String bearerToken,
        @PathVariable("id") String albumId,
        @RequestParam(value = "limit", defaultValue = "20") int limit
    );
} 