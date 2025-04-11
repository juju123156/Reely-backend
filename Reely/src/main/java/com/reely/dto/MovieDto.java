package com.reely.dto;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@ToString
public class MovieDto {

    // 영화 ID
    private String movieId;
    // 영화명 (국문)
    private String movieKoNm;    
    // 영화명 (영문)     
    private String movieEnNm;         
    // 제작년도
    private String moviePrDt;      
    // 러닝타임 (분)   
    private Integer movieRuntime;  
    // 개봉일  
    private String movieOpenDt;
    // 감독 이름    
    private String  movieAutids;
    
    // 감독 이름 (복수일 수 있음)
    private List<HashMap<String, String>> movieAutidsList;

    // 감독 고유번호
    private String movieAutidsNo;

    // 관람 등급
    private String movieWarchGrd;

    // 줄거리
    private String moviePlot;

    // 누적 관객 수
    private Long movieAudienceCnt;

    // 언어
    private String movieLanguage;

    // 수상 정보
    private List<Map<String, String>> movieAwards;

    // 상영 유형 코드
    private String showTypeCd;

    // 영화 유형 코드
    private String movieTypeCd;

    // 배우 ID
    private Long castId;

    // 배우 이름
    private String castNm;

    // 배우 한국 이름
    private String castKoNm;

    // 배우 영문 이름
    private String castEnNm;

    // 배우 한국 배역
    private String roleKoNm;

    // 배우 영문 배역
    private String roleEnNm;

    // 배우 생년일
    private String castKBirth;

    // 배우 별세일
    private String castDeath;

    // 파일
    private Long fileId;

    // 영화 이미지 ID
    private Long movieImgId;

    // 영화 이미지 type
    private Long imgType;

    // 스텝 ID
    private Long crewId;

    // 스텝 이름
    private String crewKoNm;

    // 스텝 이름
    private String crewEnNm;

    // 스텝 역할
    private String crewRole;

    // 스텝 생년일
    private String crewBirth;

    // 스텝 별세일
    private String crewDeath;

    // 감독 여부 (Y/N)
    private String crewDirectorYn;

    // 제작국가 ID
    private Long countryId;

    // 제작국가 코드
    private Long countryCd;

    // 제작국가 이름
    private Long countryNm;

    // 원산국 여부 (Y/N)
    private String originalCountryYn;

    // 영화 그룹코드
    private String groComCd;

    // 영화 공통코드
    private String comCd;

    // 영화사 ID
    private Long productionId;

    // 영화사 한국 이름
    private String productionKoNm;

    // 영화사 영문 이름
    private String productionEnNm;

    // 영화 검색 ID
    private Long movieSearchId;

    // 사운드트랙 ID
    private Long soundTrackId;


    /* Kobis */
    // 제작상태명
    private String prdtStatNm;

    // 영화유형명
    private String typeNm;

    // 영화장르 (전체)
    private String genreAlt;

    // 배우
    private List<Map<String, String>> actors;

    // 상영형태 구분
    private String showTypes;

    // 상영형태 구분명
    private String showTypeGroupNm;

    // 상영형태명
    private String showTypeNm;

    // 관람등급 명칭
    private String watchGradeNm;

    // 참여 영화사 분야명
    private String companyPartNm;

    /** 박스오피스 */
    /** 박스오피스 종류 */
    private String boxofficeType;

    /** 박스오피스 조회 일자 (yyyyMMdd-yyyyMMdd 형식) */
    private String showRange;

    /** 순번 */
    private String rnum;

    /** 해당일자의 박스오피스 순위 */
    private String rank;

    /** 전일 대비 순위 증감분 */
    private String rankInten;

    /** 랭킹 신규 진입 여부 ("OLD" 또는 "NEW") */
    private String rankOldAndNew;

    /** 해당일의 매출액 */
    private String salesAmt;

    /** 해당 영화의 매출 비율 (전체 대비 %) */
    private String salesShare;

    /** 전일 대비 매출액 증감분 */
    private String salesInten;

    /** 전일 대비 매출 증감 비율 (%) */
    private String salesChange;

    /** 누적 매출액 */
    private String salesAcc;

    /** 해당일의 관객 수 */
    private String audiCnt;

    /** 전일 대비 관객 수 증감분 */
    private String audiInten;

    /** 전일 대비 관객 수 증감 비율 (%) */
    private String audiChange;

    /** 누적 관객 수 */
    private String audiAcc;
    
    /* Kmdb */
    // 영상 내 에피소드
    private String episodes;

    // 심의여부
    private String ratedYn;

    // 대표심의일
    private String repRatDate;

    // 대표심의정보 여부
    private String ratingMain;

    // 키워드
    private String keywords;

    // 포스터이미지URL
    private String posterUrl;

    // 스틸이미지URL
    private String stillUrl;

    // 스텝기타
    private String staffEtc;

    // VOD 구분
    private String vodClass;

    // VOD URL
    private String vodUrl;

    // 기준일
    private String statDate;

    // 주제곡
    private String themeSong;

    // 삽입곡
    private String soundtrack;

    // 촬영장소
    private String fLocation;


}
