<?php if ( ! defined( 'ABSPATH' ) ) exit; get_header(); ?>

<article class="tdf-page">
	<p class="tdf-post-meta">Error 404</p>
	<h1 style="margin-top:0">That page didn't load.</h1>
	<p>The post or page you're looking for either moved, was renamed, or never existed. Try the search below or hop back to the main TrackdayFinder site for upcoming trackdays.</p>

	<form role="search" method="get" class="tdf-search" action="<?php echo esc_url( home_url( '/' ) ); ?>">
		<input type="search" name="s" placeholder="Search posts…" value="<?php echo esc_attr( get_search_query() ); ?>">
		<button type="submit">Search</button>
	</form>

	<p style="margin-top:18px">
		<a class="tdf-readmore" href="<?php echo esc_url( home_url( '/' ) ); ?>">Blog home</a>
		&nbsp;
		<a class="tdf-readmore" style="background:#0b1220" href="https://trackdayfinder.co.uk/">Main site</a>
	</p>
</article>

<?php get_footer(); ?>
