package com.reely.mapper;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;

import com.reely.dto.MovieDto;

@Mapper
public interface MovieMapper {

    int insertCountryInfo(MovieDto movieDto);
    int insertProductionInfo(List<MovieDto> movieDto);
    int insertMovieProductionInfo(List<MovieDto> movieDto);
    int insertFileInfo(List<MovieDto>  movieDto);
    int insertCastImg(List<MovieDto> movieDto);
    void insertCastInfo(List<MovieDto> movieDto);
    void insertCastMovieInfo(List<MovieDto> movieDto);
    void insertCrewInfo(List<MovieDto> movieDto);
    void insertCrewMovieInfo(List<MovieDto> movieDto);
    Integer getMovieId();
    Integer getProductionId();
    Integer getCrewId();
    Integer getCastId();
    Integer getFileId();
    Integer getSoundtrackId();
    Integer getAlbumId();
    int insertSoundtrackImg(List<MovieDto> movieDto);
    int insertSoundtrackInfo(List<MovieDto> movieDto);
    MovieDto getMovieInfo(int movieId);
    Integer insertMovieInfo(MovieDto movieDto);
}
