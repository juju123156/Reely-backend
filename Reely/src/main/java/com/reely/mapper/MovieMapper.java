package com.reely.mapper;

import java.util.List;
import java.util.Map;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import com.reely.dto.MovieDto;

@Mapper
public interface MovieMapper {

    Integer insertCountryInfo(MovieDto movieDto);
    Integer insertProductionInfo(List<MovieDto> movieDto);
    Integer insertMovieProductionInfo(List<MovieDto> movieDto);
    Integer insertFileInfo(List<MovieDto>  movieDto);
    Integer insertCastImg(List<MovieDto> movieDto);
    void insertCastInfo(List<MovieDto> movieDto);
    void insertCastMovieInfo(List<MovieDto> movieDto);
    void insertCrewInfo(List<MovieDto> movieDto);
    void insertCrewImg(List<MovieDto> movieDto);
    void insertCrewMovieInfo(List<MovieDto> movieDto);
    Integer getMovieId();
    Integer getProductionId();
    Integer getCrewId();
    Integer getCastId();
    Integer getFileId();
    Integer getSoundtrackId();
    Integer getAlbumId();
    Integer insertSoundtrackImg(List<MovieDto> movieDto);
    Integer insertSoundtrackInfo(List<MovieDto> movieDto);
    MovieDto getMovieInfo(int movieId);
    Integer insertMovieInfo(MovieDto movieDto);
    List<MovieDto> searchMoviesFlexible(Map<String, Object> params);
}