package com.reely.service;

import org.springframework.stereotype.Service;

import com.reely.dto.MovieDto;
import com.reely.dto.SpotifyDto;
import com.reely.dto.SpotifyDto.SpotifyAlbumTracksDto;

public interface MovieService {

    SpotifyDto getMovieOst(String movieNm);
    SpotifyAlbumTracksDto getSpotifyAlbumTracks(String albumId, int limit);
    int insertFileInfo(MovieDto movieDto);









}