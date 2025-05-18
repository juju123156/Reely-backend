package com.reely.mapper;

import org.apache.ibatis.annotations.Mapper;

import com.reely.dto.MovieDto;

@Mapper
public interface MovieMapper {

    int insertCountryInfo(MovieDto movieDto);
    int insertProductionInfo(MovieDto movieDto);
    int insertFileInfo(MovieDto movieDto);
    int insertCastImg(MovieDto movieDto);
    void insertCastInfo(MovieDto movieDto);
    void insertCastMovieInfo(MovieDto movieDto);
    void insertCrewInfo(MovieDto movieDto);
    void insertCrewMovieInfo(MovieDto movieDto);
    Integer getMovieId();
    Integer getCrewId();
    Integer getCastId();
    Integer getFileId();
    Integer getSoundtrackId();
    Integer getAlbumId();
    int insertSoundtrackImg(MovieDto movieDto);
    int insertSoundtrackInfo(MovieDto movieDto);
}
