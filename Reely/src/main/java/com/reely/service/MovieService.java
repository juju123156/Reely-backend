package com.reely.service;

import java.util.List;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.reely.dto.MovieDto;
import com.reely.dto.SpotifyDto;
import com.reely.dto.SpotifyDto.SpotifyAlbumTracksDto;

public interface MovieService {

    SpotifyDto getMovieOst(String movieNm);
    SpotifyAlbumTracksDto getSpotifyAlbumTracks(String albumId, int limit);
    int insertFileInfo(List<MovieDto> movieDto);
    MovieDto getMovieInfo(int movieId);
    void insertCrewsInfo(int movieId, JsonNode crewNode);







}