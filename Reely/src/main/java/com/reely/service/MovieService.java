package com.reely.service;

import org.springframework.stereotype.Service;

import com.reely.dto.SpotifyDto;
import com.reely.dto.SpotifyDto.SpotifyAlbumTracksDto;

public interface MovieService {

    SpotifyDto getMovieOst(String movieNm);
    SpotifyAlbumTracksDto getSpotifyAlbumTracks(String albumId, int limit);
}